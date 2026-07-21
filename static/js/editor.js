/* BatterBox clip editor.
 * Import mode (edit.html?player_id=X&type=walkup|homerun):
 *   import (YouTube/upload) -> poll job -> wavesurfer trim w/ vendored peaks -> save clip.
 * Re-edit mode (edit.html?clip_id=N):
 *   fetch edit_context -> wavesurfer from stored source -> PATCH new trim.
 * Contract: docs/API.md. wavesurfer is vendored in static/vendor — never CDN.
 */
import { BB } from './ws.js';
import WaveSurfer from '../vendor/wavesurfer/wavesurfer.esm.js';
import RegionsPlugin from '../vendor/wavesurfer/regions.esm.js';

const params = new URLSearchParams(location.search);
const playerId = Number(params.get('player_id'));
const clipId = Number(params.get('clip_id'));
const reeditMode = clipId > 0; // ?clip_id=N re-opens a saved clip's trim
let clipType = params.get('type') === 'homerun' ? 'homerun' : 'walkup';

const banner = document.getElementById('warn-banner');
const jobStatus = document.getElementById('job-status');
const trimSection = document.getElementById('trim-section');
const readout = document.getElementById('region-readout');
const previewBtn = document.getElementById('btn-preview');
const saveBtn = document.getElementById('btn-save');

let ws = null;          // wavesurfer instance
let regions = null;
let region = null;
let jobId = null;
let pollTimer = null;

/* ---------------- helpers ---------------- */

function showBanner(msg) {
  banner.textContent = msg;
  banner.classList.add('show');
}

function setJobStatus(msg, isError = false) {
  jobStatus.textContent = msg;
  jobStatus.classList.add('show');
  jobStatus.classList.toggle('error', isError);
}

async function resolvePlayerName(pid) {
  try {
    const teams = await BB.api('/api/teams');
    for (const t of teams) {
      const players = await BB.api(`/api/teams/${t.id}/players`);
      const p = players.find((x) => x.id === pid);
      if (p) return p.name;
    }
  } catch { /* name is cosmetic */ }
  return null;
}

/* ---------------- import + job polling ---------------- */

async function startJob(promise) {
  try {
    const { job_id } = await promise;
    jobId = job_id;
    setJobStatus('Job queued…');
    pollJob();
  } catch (err) {
    setJobStatus(`Import failed: ${err.message}`, true);
  }
}

function pollJob() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    let job;
    try {
      job = await BB.api(`/api/jobs/${jobId}`);
    } catch (err) {
      setJobStatus(`Job poll failed: ${err.message}`, true);
      return;
    }
    if (job.status === 'done') {
      setJobStatus('Audio ready — trim below.');
      initEditor(job);
    } else if (job.status === 'error') {
      setJobStatus(`Import error: ${job.detail || 'unknown error'}`, true);
    } else {
      setJobStatus(job.status === 'processing' ? 'Processing audio…' : 'Job queued…');
      pollJob();
    }
  }, 1000);
}

document.getElementById('btn-yt').addEventListener('click', () => {
  const url = document.getElementById('yt-url').value.trim();
  if (!url) { setJobStatus('Paste a YouTube URL first.', true); return; }
  startJob(BB.api('/api/clips/import/youtube', {
    method: 'POST',
    body: { player_id: playerId, type: clipType, url },
  }));
});

document.getElementById('btn-upload').addEventListener('click', () => {
  const f = document.getElementById('file-input').files[0];
  if (!f) { setJobStatus('Pick an mp3/m4a file first.', true); return; }
  const fd = new FormData();
  fd.append('file', f);
  startJob(BB.api(`/api/clips/import/upload?player_id=${playerId}&type=${clipType}`, {
    method: 'POST',
    formData: fd,
  }));
});

/* ---------------- wavesurfer trim editor ---------------- */

function fmt(sec) { return sec.toFixed(1); }

function updateReadout() {
  if (!region) return;
  readout.textContent =
    `Region: ${fmt(region.start)}s → ${fmt(region.end)}s (${fmt(region.end - region.start)}s)`;
}

function initEditor(job) {
  trimSection.hidden = false;
  if (ws) { ws.destroy(); ws = null; region = null; }

  ws = WaveSurfer.create({
    container: '#wave',
    url: job.source_audio_url,          // needed for preview playback
    peaks: [job.peaks],                 // instant waveform, no decode wait
    duration: job.duration_sec,
    height: 160,
    waveColor: '#38bdf8',
    progressColor: '#1d4ed8',
    cursorColor: '#f5f7fa',
  });

  regions = RegionsPlugin.create();
  ws.registerPlugin(regions);

  ws.on('ready', () => {
    region = regions.addRegion({
      start: job.suggested_start,
      end: job.suggested_end,
      color: 'rgba(255, 183, 3, 0.30)',
      drag: true,
      resize: true,
    });
    region.on('update', updateReadout);
    updateReadout();
    trimSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  ws.on('play', () => { previewBtn.innerHTML = '&#9632; Stop Preview'; });
  ws.on('pause', () => { previewBtn.innerHTML = '&#9654; Preview Region'; });

  ws.on('error', (e) => showBanner(`Audio load error: ${e && e.message ? e.message : e}`));
}

previewBtn.addEventListener('click', () => {
  if (!ws || !region) return;
  if (ws.isPlaying()) ws.pause();
  else ws.play(region.start, region.end); // core stops at end; plugin's region.play() drops end when called w/o args
});

saveBtn.addEventListener('click', async () => {
  if (!region || (!reeditMode && jobId == null)) return;
  const body = {
    trim_start_sec: region.start,
    trim_end_sec: region.end,
    fade_in_ms: Number(document.getElementById('fade-in').value) || 0,
    fade_out_ms: Number(document.getElementById('fade-out').value) || 0,
    volume_boost_db: Number(document.getElementById('boost').value) || 0,
  };
  if (!(body.trim_end_sec > body.trim_start_sec)) {
    showBanner('Region end must be after region start.');
    return;
  }
  saveBtn.disabled = true;
  try {
    if (reeditMode) {
      await BB.api(`/api/clips/${clipId}`, { method: 'PATCH', body });
    } else {
      await BB.api('/api/clips', {
        method: 'POST',
        body: { job_id: jobId, player_id: playerId, type: clipType, ...body },
      });
    }
    location.href = 'admin.html';
  } catch (err) {
    saveBtn.disabled = false;
    showBanner(`Save failed: ${err.message}`);
  }
});

/* ---------------- re-edit mode (?clip_id=N) ---------------- */

async function bootReedit() {
  document.getElementById('import-section').style.display = 'none';
  let ctx;
  try {
    ctx = await BB.api(`/api/clips/${clipId}/edit_context`);
  } catch (err) {
    showBanner(`Cannot re-edit this clip: ${err.message}`);
    return;
  }
  const clip = ctx.clip;
  clipType = clip.type;
  const name = await resolvePlayerName(clip.player_id);
  document.getElementById('editor-title').textContent =
    `Clip Editor — ${name || `Player #${clip.player_id}`} · ${clipType.toUpperCase()} · Edit trim`;
  document.getElementById('fade-in').value = clip.fade_in_ms;
  document.getElementById('fade-out').value = clip.fade_out_ms;
  document.getElementById('boost').value = clip.volume_boost_db;
  saveBtn.textContent = 'SAVE TRIM';
  initEditor({
    source_audio_url: ctx.source_audio_url,
    peaks: ctx.peaks,
    duration_sec: ctx.duration_sec,
    suggested_start: clip.trim_start_sec,
    suggested_end: clip.trim_end_sec,
  });
}

/* ---------------- boot ---------------- */

(async () => {
  if (reeditMode) {
    await bootReedit();
    return;
  }
  if (!playerId) {
    showBanner('Missing player_id — open this page from Admin → Add Clip.');
    document.getElementById('import-section').style.display = 'none';
    return;
  }
  const name = await resolvePlayerName(playerId);
  document.getElementById('editor-title').textContent =
    `Clip Editor — ${name || `Player #${playerId}`} · ${clipType.toUpperCase()}`;
})();
