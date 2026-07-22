"""Playback state machine, WebSocket broadcast, and server-side mpv backend.

Playback state lives ONLY here (server-side). Clients mirror it via /ws
messages. Safe to call from any thread: broadcasts are marshalled onto the
uvicorn event loop, and the mpv backend degrades to a warning broadcast
instead of crashing when mpv or an audio device is missing.
"""

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import threading

from .. import config, db

log = logging.getLogger("batterbox.audio")


class WSManager:
    def __init__(self) -> None:
        self.clients: set = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws) -> None:
        self.clients.discard(ws)

    def broadcast(self, msg: dict) -> None:
        """Thread-safe broadcast; no-op before the event loop is up."""
        loop = self.loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(msg), loop)

    async def _broadcast(self, msg: dict) -> None:
        text = json.dumps(msg)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


ws_manager = WSManager()

_lock = threading.RLock()  # guards _state / _mpv_proc / _mpv_ipc reads+writes
# Serializes complete play/stop transitions. Without it, two overlapping play
# requests can interleave stop/start and leave an untracked mpv process
# playing over the PA that STOP can no longer reach.
_op_lock = threading.Lock()
_mpv_proc: subprocess.Popen | None = None
_mpv_ipc: str | None = None

_state = {
    "status": "idle",  # idle | playing
    "clip_id": None,
    "player_id": None,
    "type": None,
    # Monotonic per-play token. Browser clients echo it back with the stop
    # they post on `ended`, so a stale end-of-song from the PREVIOUS clip
    # (slow phone, delayed request) can't kill the one playing now.
    "play_id": 0,
    "audio_warning": None,
}


def get_state() -> dict:
    with _lock:
        state = dict(_state)
    state["volume"] = int(db.get_setting("master_volume", "80"))
    return state


def _warn(message: str) -> None:
    log.warning("%s", message)
    with _lock:
        _state["audio_warning"] = message
    ws_manager.broadcast({"event": "warning", "message": message})


# --------------------------------------------------------------- mpv IPC


def _mpv_command(payload: dict) -> None:
    """Best-effort JSON IPC to a running mpv; failures only log."""
    ipc = _mpv_ipc
    if not ipc:
        return
    try:
        if os.name == "nt":
            # mpv on Windows listens on a named pipe (\\.\pipe\name).
            with open(ipc, "r+b", buffering=0) as f:
                f.write((json.dumps(payload) + "\n").encode())
        else:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1.0)
            try:
                s.connect(ipc)
                s.sendall((json.dumps(payload) + "\n").encode())
            finally:
                s.close()
    except Exception as e:  # noqa: BLE001 - never crash on IPC failure
        log.warning("mpv IPC failed: %s", e)


def _server_play(clip: dict, subdir: str = "clips") -> subprocess.Popen | None:
    """Start mpv for a clip (Pi option). Returns the process, or None if it
    could not start (warning already broadcast). Does NOT arm the EOF
    watcher — the caller does that after broadcasting the play event, so an
    instantly-exiting mpv can't emit its stop before the play."""
    global _mpv_proc, _mpv_ipc
    if shutil.which("mpv") is None:
        _warn("mpv not found; AUDIO_BACKEND=server requires mpv in the container")
        return None
    audio_path = os.path.join(config.DATA_DIR, subdir, f"{clip['id']}.mp3")
    if not os.path.exists(audio_path):
        _warn(f"clip file missing: {audio_path}")
        return None
    if os.name == "nt":
        ipc = r"\\.\pipe\batterbox-mpv"
    else:
        ipc = os.path.join(config.DATA_DIR, "mpv.sock")
        if os.path.exists(ipc):
            os.remove(ipc)
    cmd = [
        "mpv",
        "--no-terminal",
        "--really-quiet",
        f"--input-ipc-server={ipc}",
        f"--volume={int(db.get_setting('master_volume', '80'))}",
    ]
    audio_output = db.get_setting("audio_output", config.AUDIO_OUTPUT)
    if audio_output and audio_output != "auto":
        cmd.append(f"--audio-device={audio_output}")
    boost = clip.get("volume_boost_db") or 0.0
    if boost:
        cmd.append(f"--af=volume={boost}dB")
    cmd.append(audio_path)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:  # noqa: BLE001
        _warn(f"failed to start mpv: {e}")
        return None
    with _lock:
        _mpv_proc = proc
        _mpv_ipc = ipc
    return proc


def _watch_mpv(proc: subprocess.Popen) -> None:
    """Clear "playing" state when mpv reaches end of file on its own.

    The browser backend clears state via the client's `ended` handler; the
    server backend has no client to do that, so without this the state (and
    every kiosk's playing indicator) would stick until the next play/stop.
    """
    global _mpv_proc, _mpv_ipc
    proc.wait()
    # Check-and-clear atomically: check-then-stop() would leave a window
    # where a clip started in between gets killed by this watcher. proc has
    # already exited, so there is nothing to terminate. Broadcasting under
    # the lock keeps this stop ordered before any subsequent play event.
    with _lock:
        if _mpv_proc is not proc:
            return  # replaced or stopped while we waited; not ours to clear
        _mpv_proc = None
        _mpv_ipc = None
        _state.update(status="idle", clip_id=None, player_id=None, type=None)
        ws_manager.broadcast({"event": "stop"})


# ------------------------------------------------------------ operations


def _halt() -> None:
    """Tear down current playback and broadcast stop. Callers hold _op_lock."""
    global _mpv_proc, _mpv_ipc
    with _lock:
        proc = _mpv_proc
        _mpv_proc = None
        _mpv_ipc = None
        _state.update(status="idle", clip_id=None, player_id=None, type=None)
    if proc is not None:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    ws_manager.broadcast({"event": "stop"})


def stop(play_id: int | None = None) -> dict:
    """Halt playback immediately and broadcast a stop event.

    With `play_id` (browser `ended` reports), the stop only applies while
    that same play is still current — a stale end-of-song can't stop the
    next clip. Manual stops (STOP button, GPIO) pass None: always stop."""
    with _op_lock:
        if play_id is not None:
            with _lock:
                stale = _state["status"] != "playing" or _state["play_id"] != play_id
            if stale:
                return get_state()
        _halt()
    return get_state()


def _start(row: dict, subdir: str, player_id: int | None, ctype: str) -> dict:
    """One complete, serialized play transition: stop whatever is playing,
    start the new clip, commit state, broadcast, arm the EOF watcher.
    Without _op_lock two overlapping plays can interleave and orphan an mpv
    process that STOP can no longer reach."""
    with _op_lock:
        _halt()
        proc = None
        if config.AUDIO_BACKEND == "server":
            proc = _server_play(row, subdir)
            if proc is None:
                # mpv could not start: stay idle honestly (warning already
                # broadcast) instead of reporting a playback that isn't
                # happening — a stuck "playing" state never clears itself.
                return get_state()
        with _lock:
            play_id = _state["play_id"] + 1
            _state.update(
                status="playing",
                clip_id=row["id"],
                player_id=player_id,
                type=ctype,
                play_id=play_id,
                audio_warning=None,
            )
        ws_manager.broadcast(
            {
                "event": "play",
                "clip_id": row["id"],
                "player_id": player_id,
                "type": ctype,
                "play_id": play_id,
                "audio_url": row["audio_url"],
                "volume": int(db.get_setting("master_volume", "80")),
                "volume_boost_db": row["volume_boost_db"] or 0.0,
            }
        )
        if proc is not None:
            threading.Thread(
                target=_watch_mpv, args=(proc,), daemon=True, name="mpv-watcher"
            ).start()
    return get_state()


def _play_clip_row(clip: dict) -> dict:
    return _start(clip, "clips", clip["player_id"], clip["type"])


def play(player_id: int, clip_type: str) -> dict | None:
    """Play the player's active clip of `clip_type`. None if none exists."""
    if db.get_player(player_id) is None:
        return None
    clip = db.get_active_clip(player_id, clip_type)
    if clip is None:
        return None
    return _play_clip_row(clip)


def play_clip(clip_id: int) -> dict | None:
    clip = db.get_clip(clip_id)
    if clip is None:
        return None
    return _play_clip_row(clip)


def play_hype(hype_id: int) -> dict | None:
    """Play a hype clip (crowd stinger; not tied to any player)."""
    hype = db.get_hype(hype_id)
    if hype is None:
        return None
    return _start(hype, "hype", None, "hype")


def set_volume(volume: int) -> dict:
    volume = max(0, min(100, int(volume)))
    db.set_setting("master_volume", str(volume))
    with _lock:
        has_proc = _mpv_proc is not None
    if config.AUDIO_BACKEND == "server" and has_proc:
        _mpv_command({"command": ["set_property", "volume", volume]})
    ws_manager.broadcast({"event": "volume", "volume": volume})
    return get_state()


def play_next() -> tuple[dict | None, str | None]:
    """Next player in the active team's batting order (wrapping) that has an
    active walkup clip. Returns (state, error)."""
    team_id = db.get_active_team_id()
    if team_id is None:
        return None, "no active team"
    players = db.list_players(team_id)
    candidates = {
        p["id"]
        for p in players
        if p["active_walkup_clip_id"] is not None and not p.get("absent")
    }
    if not candidates:
        return None, "no players with an active walkup clip"
    order = [p["id"] for p in players]
    with _lock:
        current = _state["player_id"] if _state["status"] == "playing" else None
    if current in order:
        idx = order.index(current)
        scan = order[idx + 1 :] + order[: idx + 1]  # wraps around
    else:
        scan = order
    for pid in scan:
        if pid in candidates:
            return play(pid, "walkup"), None
    return None, "no players with an active walkup clip"
