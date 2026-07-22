"""Clip pipeline: async import jobs (yt-dlp / upload), waveform analysis,
and the ffmpeg slice+fade+loudnorm render.

Jobs run on a small in-process thread pool; status lives in a module-level
dict (jobs are ephemeral — they don't need to survive a restart). All ffmpeg
/ ffprobe / yt-dlp failures land in job status=error with a detail message;
nothing here raises into the request path uncaught.
"""

import json
import logging
import os
import subprocess
import time
import uuid
from array import array
from concurrent.futures import ThreadPoolExecutor

from .. import config, db

log = logging.getLogger("batterbox.clipper")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clipper")
_jobs: dict[str, dict] = {}

PEAK_BUCKETS = 800
PCM_RATE = 8000  # mono s16le decode rate for analysis

# What the import pipeline accepts as an uploaded source (shared by the
# clips and hype routers). Sources are full songs/mixes people trim from;
# 50MB ≈ 20+ min at 320kbps.
UPLOAD_EXTS = {".mp3", ".m4a"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Jobs are only needed between import and POST /api/clips|/api/hype; anything
# this old is abandoned (or stuck). Evicting just drops the dict entry — the
# source file stays on disk for clips that already reference it.
JOB_TTL_SEC = 60 * 60


def _evict_stale_jobs() -> None:
    cutoff = time.monotonic() - JOB_TTL_SEC
    stale = [jid for jid, j in _jobs.items() if j["created_mono"] < cutoff]
    for jid in stale:
        del _jobs[jid]
    if stale:
        log.info("evicted %d stale import job(s)", len(stale))


class JobError(Exception):
    """Raised for client-facing job problems (unknown id, not done, ...)."""


class RenderError(Exception):
    """Raised when the ffmpeg render pass fails."""


class SourceMissingError(Exception):
    """Raised when a clip's stored source file is absent (or never recorded)."""


# -------------------------------------------------------------- job intake


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def job_public(job: dict) -> dict:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "detail": job.get("detail", ""),
        "duration_sec": job.get("duration_sec"),
        "suggested_start": job.get("suggested_start"),
        "suggested_end": job.get("suggested_end"),
        "source_audio_url": job.get("source_audio_url"),
        "peaks": job.get("peaks"),
    }


def _new_job(source: str, source_url: str | None) -> dict:
    _evict_stale_jobs()
    job = {
        "job_id": uuid.uuid4().hex[:12],
        "status": "pending",
        "detail": "",
        "source": source,
        "source_url": source_url,
        "created_mono": time.monotonic(),
    }
    _jobs[job["job_id"]] = job
    return job


def start_youtube_job(player_id: int, clip_type: str, url: str) -> dict:
    job = _new_job("youtube", url)
    _executor.submit(_run_youtube, job)
    return job


def start_upload_job(player_id: int, clip_type: str, ext: str, data: bytes) -> dict:
    job = _new_job("upload", None)
    path = os.path.join(config.DATA_DIR, "sources", job["job_id"] + ext)
    with open(path, "wb") as f:
        f.write(data)
    _executor.submit(_analyze, job, path)
    return job


# Hype imports run through the exact same job pipeline; the title is collected
# again at create time, so the job itself doesn't need to carry it.

def start_hype_youtube_job(url: str) -> dict:
    job = _new_job("youtube", url)
    _executor.submit(_run_youtube, job)
    return job


def start_hype_upload_job(ext: str, data: bytes) -> dict:
    job = _new_job("upload", None)
    path = os.path.join(config.DATA_DIR, "sources", job["job_id"] + ext)
    with open(path, "wb") as f:
        f.write(data)
    _executor.submit(_analyze, job, path)
    return job


# ------------------------------------------------------------------ stages


def _run_youtube(job: dict) -> None:
    job["status"] = "processing"
    try:
        import yt_dlp
    except ImportError:
        job["status"] = "error"
        job["detail"] = "yt-dlp is not installed"
        return
    out_tmpl = os.path.join(config.DATA_DIR, "sources", job["job_id"] + ".%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([job["source_url"]])
    except Exception as e:  # noqa: BLE001 - yt-dlp raises many types
        job["status"] = "error"
        job["detail"] = f"yt-dlp failed: {e}"
        return
    path = os.path.join(config.DATA_DIR, "sources", job["job_id"] + ".mp3")
    if not os.path.exists(path):
        job["status"] = "error"
        job["detail"] = "yt-dlp did not produce an mp3 (is ffmpeg installed?)"
        return
    _analyze(job, path)


def _ffprobe_duration(path: str) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json", path,
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RenderError(f"ffprobe failed: {proc.stderr.strip()[:300]}")
    return float(json.loads(proc.stdout)["format"]["duration"])


def _decode_pcm(path: str) -> array:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path,
         "-f", "s16le", "-ac", "1", "-ar", str(PCM_RATE), "pipe:1"],
        capture_output=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg decode failed: {proc.stderr.decode(errors='replace').strip()[:300]}")
    samples = array("h")
    samples.frombytes(proc.stdout)
    return samples


def _analyze(job: dict, path: str) -> None:
    job["status"] = "processing"
    snippet = float(db.get_setting("default_snippet_length", "30"))
    try:
        duration = _ffprobe_duration(path)
        job["duration_sec"] = round(duration, 3)
        samples = _decode_pcm(path)
        job["peaks"] = _peaks(samples)
        start = _loudest_window(samples, duration, snippet)
        if start is None:
            start = 0.0  # fallback: 0 -> default_snippet_length
        job["suggested_start"] = round(start, 1)
        job["suggested_end"] = round(min(start + snippet, duration), 1)
        job["source_audio_url"] = "/media/sources/" + os.path.basename(path)
        job["source_path"] = path
        job["status"] = "done"
    except FileNotFoundError as e:
        job["status"] = "error"
        job["detail"] = f"missing binary: {e.filename or e} (ffmpeg/ffprobe required)"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["detail"] = str(e)
        log.warning("analysis failed for job %s: %s", job["job_id"], e)


def _peaks(samples: array) -> list[float]:
    """~800 normalized (0..1) max-amplitude buckets for waveform rendering."""
    n = len(samples)
    if n == 0:
        return []
    bucket = max(1, -(-n // PEAK_BUCKETS))
    peaks = []
    for i in range(0, n, bucket):
        chunk = samples[i : i + bucket]
        if not chunk:
            break
        # max()/min() over array slices run at C speed
        peak = max(max(chunk), -min(chunk)) / 32768.0
        peaks.append(round(min(1.0, peak), 3))
    return peaks


def _loudest_window(samples: array, duration: float, snippet: float) -> float | None:
    """Start (seconds) of the loudest `snippet`-long window, by 1s-window RMS."""
    n = len(samples)
    win = PCM_RATE  # 1 second of samples
    n_windows = n // win
    if n_windows < 2:
        return None
    rms = []
    for w in range(n_windows):
        chunk = samples[w * win : (w + 1) * win]
        rms.append(sum(x * x for x in chunk) / len(chunk))
    span = max(1, int(snippet))
    if span >= n_windows:
        return None
    best_start, best_sum = 0, -1.0
    cur = sum(rms[:span])
    for i in range(0, n_windows - span + 1):
        if i > 0:
            cur += rms[i + span - 1] - rms[i - 1]
        if cur > best_sum:
            best_sum, best_start = cur, i
    return float(best_start)


# ------------------------------------------------------------------ render


def _render(
    src: str,
    dst: str,
    trim_start_sec: float,
    trim_end_sec: float,
    duration: float,
    fade_in_ms: int,
    fade_out_ms: int,
) -> None:
    """One ffmpeg pass: slice + afade + loudnorm -> 192k MP3 at `dst`."""
    filters = []
    if fade_in_ms > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in_ms / 1000:.3f}")
    if fade_out_ms > 0:
        out_st = max(0.0, duration - fade_out_ms / 1000)
        filters.append(f"afade=t=out:st={out_st:.3f}:d={fade_out_ms / 1000:.3f}")
    filters.append("loudnorm")  # EBU R128
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{trim_start_sec:.3f}", "-to", f"{trim_end_sec:.3f}",
        "-i", src, "-vn",
        "-af", ",".join(filters),
        "-b:a", "192k", dst,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        raise RenderError("ffmpeg is not installed") from None
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg render failed: {proc.stderr.strip()[:500]}")


def _source_path(source_file: str | None) -> str:
    if not source_file:
        raise SourceMissingError(
            "clip has no stored source file (saved before re-edit support)"
        )
    path = os.path.join(config.DATA_DIR, "sources", source_file)
    if not os.path.exists(path):
        raise SourceMissingError(
            f"source file '{source_file}' no longer exists on disk"
        )
    return path


def _edit_context(source_file: str | None, key: str, obj: dict) -> dict:
    """Everything the editor needs to re-open a saved clip/hype trim."""
    path = _source_path(source_file)
    try:
        duration = _ffprobe_duration(path)
        peaks = _peaks(_decode_pcm(path))
    except FileNotFoundError as e:
        raise RenderError(
            f"missing binary: {e.filename or e} (ffmpeg/ffprobe required)"
        ) from None
    return {
        key: obj,
        "source_audio_url": "/media/sources/" + os.path.basename(path),
        "duration_sec": round(duration, 3),
        "peaks": peaks,
    }


def edit_context(clip_id: int) -> dict:
    return _edit_context(db.get_clip_source_file(clip_id), "clip", db.get_clip(clip_id))


def edit_context_hype(hype_id: int) -> dict:
    return _edit_context(db.get_hype_source_file(hype_id), "hype", db.get_hype(hype_id))


def _probe_source(src: str) -> float:
    """Source duration in seconds; RenderError if ffprobe is missing/fails."""
    try:
        return _ffprobe_duration(src)
    except FileNotFoundError as e:
        raise RenderError(
            f"missing binary: {e.filename or e} (ffmpeg/ffprobe required)"
        ) from None


def _validate_trim(
    src_duration: float,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
) -> float:
    """Validate a trim against the source duration; returns the trimmed
    duration. Raises JobError (client's fault → 400)."""
    if trim_start_sec < 0:
        raise JobError("trim_start_sec must be >= 0")
    if trim_end_sec <= trim_start_sec:
        raise JobError("trim_end_sec must be greater than trim_start_sec")
    if fade_in_ms < 0 or fade_out_ms < 0:
        raise JobError("fade_in_ms and fade_out_ms must be >= 0")
    if trim_end_sec > src_duration:
        raise JobError(
            f"trim_end_sec exceeds source duration ({src_duration:.3f}s)"
        )
    return round(trim_end_sec - trim_start_sec, 3)


def _render_to_file(
    src: str,
    dst_dir: str,
    item_id: int,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    src_duration: float | None = None,
) -> float:
    """Validate the trim against the source duration, then render to
    DATA_DIR/<dst_dir>/<item_id>.mp3 via temp-file-then-move so a failed render
    never leaves a half-written mp3. Returns the rendered duration.
    Pass `src_duration` if the caller already probed the source (one ffprobe
    per request, not two)."""
    if src_duration is None:
        src_duration = _probe_source(src)
    duration = _validate_trim(
        src_duration, trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms
    )
    dst = os.path.join(config.DATA_DIR, dst_dir, f"{item_id}.mp3")
    tmp = os.path.join(config.DATA_DIR, dst_dir, f"{item_id}.tmp.mp3")
    try:
        _render(src, tmp, trim_start_sec, trim_end_sec, duration, fade_in_ms, fade_out_ms)
        os.replace(tmp, dst)  # atomic-ish: never a half-written clip file
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return duration


def rerender_clip(
    clip_id: int,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
) -> dict:
    """Re-render a saved clip from its stored source with new trim settings."""
    src = _source_path(db.get_clip_source_file(clip_id))
    duration = _render_to_file(
        src, "clips", clip_id, trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms
    )
    db.update_clip_trim(
        clip_id,
        duration_sec=duration,
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
        fade_in_ms=fade_in_ms,
        fade_out_ms=fade_out_ms,
        volume_boost_db=volume_boost_db,
    )
    return db.get_clip(clip_id)


def rerender_hype(
    hype_id: int,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
) -> dict:
    """Re-render a saved hype clip from its stored source with new trim."""
    src = _source_path(db.get_hype_source_file(hype_id))
    duration = _render_to_file(
        src, "hype", hype_id, trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms
    )
    db.update_hype_trim(
        hype_id,
        duration_sec=duration,
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
        fade_in_ms=fade_in_ms,
        fade_out_ms=fade_out_ms,
        volume_boost_db=volume_boost_db,
    )
    return db.get_hype(hype_id)


def _done_job_source(job_id: str) -> tuple[dict, str]:
    job = _jobs.get(job_id)
    if job is None:
        raise JobError("unknown job_id")
    if job["status"] != "done":
        raise JobError(f"job is not done (status={job['status']}: {job.get('detail', '')})")
    return job, job["source_path"]


def create_clip(
    job_id: str,
    player_id: int,
    clip_type: str,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
) -> dict:
    job, src = _done_job_source(job_id)
    # Same validation as PATCH (incl. trim vs source duration) — fail fast
    # with a clean 400 before touching the DB, not a 500 out of ffmpeg.
    src_duration = _probe_source(src)
    duration = _validate_trim(
        src_duration, trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms
    )
    is_first = db.count_clips(player_id, clip_type) == 0
    clip_id = db.insert_clip(
        player_id=player_id,
        clip_type=clip_type,
        is_active=is_first,  # first clip of player+type becomes active
        source=job["source"],
        source_url=job["source_url"],
        duration_sec=duration,
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
        fade_in_ms=fade_in_ms,
        fade_out_ms=fade_out_ms,
        volume_boost_db=volume_boost_db,
        source_file=os.path.basename(src),
    )
    try:
        _render_to_file(
            src, "clips", clip_id, trim_start_sec, trim_end_sec,
            fade_in_ms, fade_out_ms, src_duration=src_duration,
        )
    except Exception:
        db.delete_clip(clip_id)
        raise
    return db.get_clip(clip_id)


def create_hype(
    job_id: str,
    title: str,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
) -> dict:
    job, src = _done_job_source(job_id)
    title = title.strip()
    if not title or len(title) > 80:
        raise JobError("title must be 1–80 characters")
    src_duration = _probe_source(src)
    duration = _validate_trim(
        src_duration, trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms
    )
    hype_id = db.insert_hype(
        title=title,
        source=job["source"],
        source_url=job["source_url"],
        duration_sec=duration,
        trim_start_sec=trim_start_sec,
        trim_end_sec=trim_end_sec,
        fade_in_ms=fade_in_ms,
        fade_out_ms=fade_out_ms,
        volume_boost_db=volume_boost_db,
        source_file=os.path.basename(src),
    )
    try:
        _render_to_file(
            src, "hype", hype_id, trim_start_sec, trim_end_sec,
            fade_in_ms, fade_out_ms, src_duration=src_duration,
        )
    except Exception:
        db.delete_hype(hype_id)
        raise
    return db.get_hype(hype_id)
