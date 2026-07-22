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

/* ---------------- audio playback ---------------- */

const audio = new Audio();
audio.preload = 'auto';
let lastPlayId = null;
// Song finished naturally → tell the server (same path as the STOP button)
// so every client clears the playing state: tile highlight + Walter.
// The play_id makes it conditional server-side: a slow client's ended from
// the PREVIOUS clip can no longer stop the one playing now.
audio.addEventListener('ended', () => { playback.stop(lastPlayId).catch(() => {}); });
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

function handlePlay(msg) {
  const vol = Math.max(0, Math.min(100, msg.volume ?? lastState.volume ?? 80));
  lastPlayId = msg.play_id ?? null;
  lastState = { status: 'playing', clip_id: msg.clip_id, player_id: msg.player_id, type: msg.type, volume: vol };
  audio.volume = vol / 100;
  const boost = Number(msg.volume_boost_db) || 0;
  if (boost !== 0 || boostRouted) {
    ensureBoostGraph();
    if (gainNode) {
      gainNode.gain.value = boost !== 0 ? Math.pow(10, boost / 20) : 1;
      if (actx && actx.state === 'suspended') actx.resume().catch(() => {});
    }
  }
  audio.src = msg.audio_url;
  audio.currentTime = 0;
  audio.play().catch((e) => console.warn('audio.play() rejected', e));
}

function handleStop() {
  // Halt immediately (well under the 200ms budget).
  audio.pause();
  try { audio.currentTime = 0; } catch { /* not loaded yet */ }
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
  if (msg.status !== 'playing') handleStop();
  // If status==='playing' we missed the original 'play' (page loaded mid-song) and
  // state carries no audio_url, so we reconcile the UI only, without starting audio.
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
  getVolume: () => lastState.volume ?? 80,
  getWarning: () => lastWarning,
};
