/* BatterBox shared client: WebSocket (/ws) + browser audio playback + REST helper + mock GPIO.
 * Contract: docs/API.md. Pages import { BB } from this module.
 */

const handlers = new Map(); // event -> Set<fn>
let ws = null;
let reconnectDelay = 1000;
let lastState = { status: 'idle', clip_id: null, player_id: null, type: null, volume: 80 };
let lastWarning = null;

/* ---------------- REST helper ---------------- */

async function api(path, { method = 'GET', body, formData } = {}) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (formData !== undefined) {
    opts.body = formData; // browser sets multipart boundary
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = (data && data.detail) ? data.detail : `HTTP ${res.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

/* ---------------- event bus ---------------- */

function on(event, fn) {
  if (!handlers.has(event)) handlers.set(event, new Set());
  handlers.get(event).add(fn);
  return () => off(event, fn);
}
function off(event, fn) {
  const s = handlers.get(event);
  if (s) s.delete(fn);
}
function emit(event, msg) {
  const s = handlers.get(event);
  if (s) for (const fn of [...s]) {
    try { fn(msg); } catch (e) { console.error('BB handler error', event, e); }
  }
}

/* ---------------- audio role ----------------
 * 'player' = this device renders the sound (the Pi kiosk); everything else
 * is a 'controller' — sends commands, mirrors state, stays silent. Default
 * is controller so a forgotten phone/admin tab can never join the PA.
 * Several devices MAY opt in at once (kiosk + a spectator on a Bluetooth
 * earpiece); no client can claim or revoke another client's role.
 *
 * The role belongs to the DEVICE, not to one page: an explicit ?player=0|1
 * wins on load and is remembered, so the kiosk launcher's ?player=1 can't be
 * silenced by a toggle left off — and it survives the walk from the kiosk to
 * ADMIN and back (only index.html carries the toggle, so without this the
 * Pi's own admin page would be a silent controller and testing a clip from
 * the touchscreen would play nothing). Without the param the stored value
 * decides, so a phone keeps its own choice.
 */
const AUDIO_ROLE_KEY = 'bb-audio-player';

function storeAudioRole(on) {
  try { localStorage.setItem(AUDIO_ROLE_KEY, on ? '1' : '0'); } catch { /* blocked */ }
}

function detectAudioRole() {
  const param = new URLSearchParams(location.search).get('player');
  if (param === '1' || param === '0') {
    const on = param === '1';
    storeAudioRole(on); // the whole device follows this page's instruction
    return on;
  }
  let stored = null;
  try { stored = localStorage.getItem(AUDIO_ROLE_KEY); } catch { /* blocked */ }
  return stored === '1';
}

let isPlayer = detectAudioRole();

function setAudioPlayer(v) {
  const was = isPlayer;
  isPlayer = !!v;
  storeAudioRole(isPlayer);
  if (!isPlayer) {
    audio.pause();
    try { audio.currentTime = 0; } catch { /* not loaded yet */ }
    activePlayId = null;
    // Deliberately NOT reporting a stop: muting this device must never end
    // the clip for the other listeners. The server ends the play on time.
  } else if (!was) {
    joinCurrentPlay();
  }
  emit('audiorole', { player: isPlayer });
}

// Opting in mid-song: pick up the clip already in progress at the offset the
// server reports, instead of standing there silent until the next batter.
async function joinCurrentPlay() {
  let s;
  try { s = await api('/api/playback/state'); } catch { return; }
  if (!isPlayer || s.status !== 'playing' || !s.audio_url) return;
  // A newer play can start while that request is in flight; its `play`
  // event already began the right clip here, so applying this now-stale
  // response would swap the crowd's song for the previous one.
  if (lastPlayId !== null && s.play_id !== lastPlayId) return;
  const offset = Number(s.elapsed_sec) || 0;
  if (s.duration_sec && offset >= s.duration_sec) return; // all but over
  lastPlayId = s.play_id ?? null;
  lastServerEos = s.server_eos === true;
  startAudio({
    playId: s.play_id,
    audioUrl: s.audio_url,
    volume: s.volume,
    boostDb: s.volume_boost_db,
    offset,
  });
}

/* ---------------- audio playback ---------------- */

const audio = new Audio();
audio.preload = 'auto';
let lastPlayId = null;
let lastServerEos = false;
// End of song is the SERVER's call whenever it knows the clip length
// (server_eos on the play event): several devices may be opted in to play,
// and reporting from here let whichever one finished first cut the song for
// all the others. Only for a clip with no stored duration does the client
// still report — play_id keeps that conditional server-side, so a late
// report from the PREVIOUS clip can't stop the one playing now.
audio.addEventListener('ended', () => {
  if (lastServerEos) return;
  playback.stop(lastPlayId).catch(() => {});
});
let actx = null;
let gainNode = null;
let boostRouted = false;

function ensureBoostGraph() {
  if (boostRouted) return;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  actx = new AC();
  const src = actx.createMediaElementSource(audio);
  gainNode = actx.createGain();
  src.connect(gainNode).connect(actx.destination);
  boostRouted = true;
}

// play_id currently loaded into the audio element, so a reconnect's `state`
// message can't restart a clip this device is already playing.
let activePlayId = null;

function startAudio({ playId = null, audioUrl, volume, boostDb, offset = 0 }) {
  if (!audioUrl) return;
  const vol = Math.max(0, Math.min(100, volume ?? lastState.volume ?? 80));
  audio.volume = vol / 100;
  const boost = Number(boostDb) || 0;
  if (boost !== 0 || boostRouted) {
    ensureBoostGraph();
    if (gainNode) {
      gainNode.gain.value = boost !== 0 ? Math.pow(10, boost / 20) : 1;
      if (actx && actx.state === 'suspended') actx.resume().catch(() => {});
    }
  }
  activePlayId = playId;
  audio.src = audioUrl;
  const start = () => audio.play().catch((e) => console.warn('audio.play() rejected', e));
  if (offset > 0) {
    // Seek before starting — seeking after play() is audible as a blip, and
    // currentTime can't be set until the metadata is in.
    audio.addEventListener('loadedmetadata', () => {
      try { audio.currentTime = offset; } catch { /* not seekable */ }
      start();
    }, { once: true });
  } else {
    audio.currentTime = 0;
    start();
  }
}

function handlePlay(msg) {
  const vol = Math.max(0, Math.min(100, msg.volume ?? lastState.volume ?? 80));
  lastPlayId = msg.play_id ?? null;
  lastServerEos = msg.server_eos === true;
  lastState = { status: 'playing', clip_id: msg.clip_id, player_id: msg.player_id, type: msg.type, volume: vol };
  if (!isPlayer) return; // controllers mirror state but never play audio
  startAudio({
    playId: msg.play_id,
    audioUrl: msg.audio_url,
    volume: vol,
    boostDb: msg.volume_boost_db,
  });
}

function handleStop() {
  // Halt immediately (well under the 200ms budget).
  audio.pause();
  try { audio.currentTime = 0; } catch { /* not loaded yet */ }
  activePlayId = null;
  lastState = { ...lastState, status: 'idle', clip_id: null, player_id: null, type: null };
}

function handleVolume(msg) {
  const vol = Math.max(0, Math.min(100, msg.volume));
  lastState = { ...lastState, volume: vol };
  audio.volume = vol / 100;
}

function handleState(msg) {
  lastState = {
    status: msg.status,
    clip_id: msg.clip_id,
    player_id: msg.player_id,
    type: msg.type,
    volume: msg.volume ?? lastState.volume,
  };
  audio.volume = (lastState.volume ?? 80) / 100;
  if (msg.status !== 'playing') {
    handleStop();
  } else {
    lastPlayId = msg.play_id ?? null;
    lastServerEos = msg.server_eos === true;
    // We missed the original 'play' — page loaded or reconnected mid-song.
    // A player picks the clip up at the server's offset (a kiosk that reloads
    // mid-walkup used to sit out the rest of it); the guard keeps a reconnect
    // from restarting audio this device is already playing.
    const alreadyPlaying = activePlayId === msg.play_id && !audio.paused;
    const offset = Number(msg.elapsed_sec) || 0;
    const nearlyOver = msg.duration_sec && offset >= msg.duration_sec;
    if (isPlayer && msg.audio_url && !alreadyPlaying && !nearlyOver) {
      startAudio({
        playId: msg.play_id,
        audioUrl: msg.audio_url,
        volume: lastState.volume,
        boostDb: msg.volume_boost_db,
        offset,
      });
    }
  }
  if (msg.audio_warning) {
    lastWarning = msg.audio_warning;
    emit('warning', { message: msg.audio_warning });
  }
}

const dispatch = { play: handlePlay, stop: handleStop, volume: handleVolume, state: handleState, warning: (m) => { lastWarning = m.message; } };

function handleMessage(msg) {
  if (!msg || typeof msg.event !== 'string') return;
  const internal = dispatch[msg.event];
  if (internal) internal(msg);
  emit(msg.event, msg);
}

/* ---------------- WebSocket ---------------- */

function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen = () => { reconnectDelay = 1000; emit('open', {}); };
  ws.onmessage = (ev) => {
    let msg = null;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleMessage(msg);
  };
  ws.onclose = () => {
    emit('close', {});
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 10000);
  };
  ws.onerror = () => { try { ws.close(); } catch { /* already closed */ } };
}

/* ---------------- playback REST (GPIO and UI share these) ---------------- */

const playback = {
  play: (player_id, type) => api('/api/playback/play', { method: 'POST', body: { player_id, type } }),
  playClip: (clip_id) => api('/api/playback/play_clip', { method: 'POST', body: { clip_id } }),
  playHype: (hype_id) => api('/api/playback/play_hype', { method: 'POST', body: { hype_id } }),
  // play_id: only the automatic `ended` reporter passes one; manual STOP
  // (buttons, GPIO, keyboard) omits it and always stops.
  stop: (play_id) => api('/api/playback/stop', {
    method: 'POST',
    ...(play_id != null ? { body: { play_id } } : {}),
  }),
  next: () => api('/api/playback/next', { method: 'POST' }),
  setVolume: (volume) => api('/api/playback/volume', { method: 'POST', body: { volume: Math.max(0, Math.min(100, Math.round(volume))) } }),
  changeVolume: (delta) => playback.setVolume((lastState.volume ?? 80) + delta),
};

/* ---------------- mock GPIO (keyboard + debug buttons) ---------------- */

function isTypingTarget(t) {
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}

async function initMockGPIO(container) {
  let settings;
  try { settings = await api('/api/settings'); } catch { return; }
  if (!settings.mock_gpio) return;

  window.addEventListener('keydown', (e) => {
    if (isTypingTarget(e.target)) return;
    const handled = e.code === 'Space' || e.code === 'ArrowUp' || e.code === 'ArrowDown'
      || e.key === 'n' || e.key === 'N';
    if (!handled) return;
    e.preventDefault();
    // keep Space/arrows from also activating a focused button/select
    if (document.activeElement && document.activeElement !== document.body) {
      document.activeElement.blur();
    }
    if (e.code === 'Space') playback.stop().catch(() => {});
    else if (e.code === 'ArrowUp') playback.changeVolume(5).catch(() => {});
    else if (e.code === 'ArrowDown') playback.changeVolume(-5).catch(() => {});
    else playback.next().catch(() => {});
  });

  if (container) {
    container.classList.add('show');
    const label = document.createElement('span');
    label.className = 'mock-label';
    label.textContent = 'MOCK GPIO';
    container.appendChild(label);
    const mk = (text, fn) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = text;
      b.addEventListener('click', () => fn().catch(() => {}));
      container.appendChild(b);
    };
    mk('STOP', playback.stop);
    mk('VOL+', () => playback.changeVolume(5));
    mk('VOL-', () => playback.changeVolume(-5));
    mk('NEXT', playback.next);
  }
}

/* ---------------- public API ---------------- */

export const BB = {
  api,
  on,
  off,
  connect,
  playback,
  initMockGPIO,
  getState: () => ({ ...lastState }),
  isAudioPlayer: () => isPlayer,
  setAudioPlayer,
  getVolume: () => lastState.volume ?? 80,
  getWarning: () => lastWarning,
};
