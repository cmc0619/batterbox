/* BatterBox kiosk grid (index.html).
 * Modes: O = offense (tap walk-up, long-press 600ms home-run), D = defense
 * (players with an active walk-out clip; tap walk-out, long-press home-run),
 * H = hype (crowd stingers; tap to play, no long-press). Contract: docs/API.md.
 */
import { BB } from './ws.js';

const PAGE_SIZE = 15;
const LONG_PRESS_MS = 600;

const gridEl = document.getElementById('grid');
const phoneListEl = document.getElementById('phone-list');
const teamNameEl = document.getElementById('team-name');
const banner = document.getElementById('warn-banner');
const walter = document.getElementById('walter');
const pagePrev = document.getElementById('page-prev');
const pageNext = document.getElementById('page-next');
const pageIndicator = document.getElementById('page-indicator');
const modeBtns = {
  o: document.getElementById('mode-o'),
  d: document.getElementById('mode-d'),
  h: document.getElementById('mode-h'),
};

let players = [];
let hypeClips = [];
let page = 0;
let mode = 'o'; // 'o' offense | 'd' defense | 'h' hype — client-side only
let playing = null; // { type, player_id, clip_id } of the current play, or null
let bannerTimer = null;

function visiblePlayers() {
  return mode === 'd'
    ? players.filter((p) => p.active_walkout_clip_id != null)
    : players;
}

/* ---------------- helpers ---------------- */

function showBanner(msg, sticky = true) {
  banner.textContent = msg;
  banner.classList.add('show');
  if (bannerTimer) clearTimeout(bannerTimer);
  bannerTimer = null;
  if (!sticky) bannerTimer = setTimeout(hideBanner, 5000);
}
function hideBanner() {
  banner.classList.remove('show');
  if (bannerTimer) { clearTimeout(bannerTimer); bannerTimer = null; }
}

function makeAvatar(player) {
  if (player.photo_url) {
    const img = document.createElement('img');
    img.className = 'photo';
    img.src = player.photo_url;
    img.alt = '';
    img.draggable = false;
    img.addEventListener('error', () => img.replaceWith(jerseyPlaceholder(player)), { once: true });
    return img;
  }
  return jerseyPlaceholder(player);
}
function jerseyPlaceholder(player) {
  const d = document.createElement('div');
  d.className = 'jersey-ph';
  d.textContent = player.jersey_number ?? '?';
  return d;
}
function hypeAvatar() {
  const d = document.createElement('div');
  d.className = 'hype-ph';
  d.textContent = '♪';
  return d;
}

/* ---------------- tap / long-press ---------------- */

function attachPressHandlers(el, player) {
  let timer = null;
  let longFired = false;

  const clear = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    el.classList.remove('pressed');
  };

  el.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    longFired = false;
    el.classList.add('pressed'); // immediate visual feedback
    timer = setTimeout(() => {
      timer = null;
      longFired = true;
      el.classList.remove('pressed');
      BB.playback.play(player.id, 'homerun')
        .catch((err) => showBanner(err.message, false));
    }, LONG_PRESS_MS);
  });
  el.addEventListener('pointerup', () => {
    const wasLong = longFired;
    clear();
    longFired = false;
    if (wasLong) return; // suppress tap after long-press
    BB.playback.play(player.id, mode === 'd' ? 'walkout' : 'walkup')
      .catch((err) => showBanner(err.message, false));
  });
  el.addEventListener('pointercancel', clear);
  el.addEventListener('pointerleave', clear);
  el.addEventListener('contextmenu', (e) => e.preventDefault());
}

function attachHypePressHandlers(el, hype) {
  const clear = () => el.classList.remove('pressed');
  el.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    el.classList.add('pressed'); // immediate visual feedback
  });
  el.addEventListener('pointerup', () => {
    clear();
    BB.playback.playHype(hype.id)
      .catch((err) => showBanner(err.message, false));
  });
  el.addEventListener('pointercancel', clear);
  el.addEventListener('pointerleave', clear);
  el.addEventListener('contextmenu', (e) => e.preventDefault());
}

/* ---------------- render ---------------- */

function buildPlayerEl(player, kind) {
  const el = document.createElement('div');
  el.className = kind; // 'tile' or 'prow'
  el.dataset.playerId = player.id;
  el.appendChild(makeAvatar(player));
  const name = document.createElement('div');
  name.className = 'pname';
  name.textContent = player.name;
  el.appendChild(name);
  // Jersey number under the name only when a photo is shown — with the
  // jersey-circle placeholder the number is already in the circle (redundant).
  if (player.photo_url && player.jersey_number != null) {
    const num = document.createElement('div');
    num.className = 'jnum';
    num.textContent = `#${player.jersey_number}`;
    el.appendChild(num);
  }
  if (playing && playing.type !== 'hype' && playing.player_id === player.id) {
    el.classList.add('playing');
  }
  attachPressHandlers(el, player);
  return el;
}

function buildHypeEl(hype, kind) {
  const el = document.createElement('div');
  el.className = kind; // 'tile' or 'prow'
  el.dataset.hypeId = hype.id;
  el.appendChild(hypeAvatar());
  const name = document.createElement('div');
  name.className = 'pname';
  name.textContent = hype.title;
  el.appendChild(name);
  if (playing && playing.type === 'hype' && playing.clip_id === hype.id) {
    el.classList.add('playing');
  }
  attachHypePressHandlers(el, hype);
  return el;
}

function render() {
  const hypeMode = mode === 'h';
  const list = hypeMode ? hypeClips : visiblePlayers();
  const totalPages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  page = Math.min(page, totalPages - 1);
  const slice = list.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  gridEl.textContent = '';
  for (const item of slice) {
    gridEl.appendChild(hypeMode ? buildHypeEl(item, 'tile') : buildPlayerEl(item, 'tile'));
  }
  for (let i = slice.length; i < PAGE_SIZE; i++) {
    const filler = document.createElement('div');
    filler.className = 'tile empty';
    gridEl.appendChild(filler);
  }

  phoneListEl.textContent = '';
  for (const item of list) {
    phoneListEl.appendChild(hypeMode ? buildHypeEl(item, 'prow') : buildPlayerEl(item, 'prow'));
  }

  const paged = list.length > PAGE_SIZE;
  pagePrev.hidden = !paged;
  pageNext.hidden = !paged;
  pageIndicator.hidden = !paged;
  pageIndicator.textContent = `${page + 1} / ${totalPages}`;
}

function markPlaying(state) {
  // state: { type, player_id, clip_id } or null. Player tiles key off
  // player_id; hype tiles key off clip_id (hype plays carry player_id null).
  playing = state;
  for (const el of document.querySelectorAll('[data-player-id]')) {
    el.classList.toggle(
      'playing',
      !!state && state.type !== 'hype' && Number(el.dataset.playerId) === state.player_id
    );
  }
  for (const el of document.querySelectorAll('[data-hype-id]')) {
    el.classList.toggle(
      'playing',
      !!state && state.type === 'hype' && Number(el.dataset.hypeId) === state.clip_id
    );
  }
  walter.classList.toggle('playing', !!state); // dances for any playing status
}

/* ---------------- data loading ---------------- */

async function loadPlayers(teamId) {
  // absent players stay in the roster (admin) but never appear on the kiosk
  players = (await BB.api(`/api/teams/${teamId}/players`)).filter((p) => !p.absent);
  page = 0;
  render();
}

async function loadHype() {
  hypeClips = await BB.api('/api/hype');
  render();
}

async function loadTeams() {
  const [teams, active] = await Promise.all([
    BB.api('/api/teams'),
    BB.api('/api/teams/active'),
  ]);
  const selected = teams.some((t) => t.id === active.team_id)
    ? active.team_id
    : (teams[0] && teams[0].id);
  if (selected == null) {
    players = [];
    render();
    showBanner('No teams yet — open ADMIN to create one.');
    return;
  }
  const team = teams.find((t) => t.id === selected);
  teamNameEl.textContent = team ? team.name : 'BatterBox';
  await loadPlayers(selected);
}

/* ---------------- controls ---------------- */

document.getElementById('btn-stop').addEventListener('click', () => {
  BB.playback.stop().catch((err) => showBanner(err.message, false));
});
pagePrev.addEventListener('click', () => { page = Math.max(0, page - 1); render(); });
pageNext.addEventListener('click', () => {
  const len = mode === 'h' ? hypeClips.length : visiblePlayers().length;
  page = Math.min(Math.ceil(len / PAGE_SIZE) - 1, page + 1);
  render();
});

async function setMode(next) {
  if (next === mode) return;
  mode = next;
  for (const [m, btn] of Object.entries(modeBtns)) {
    btn.classList.toggle('on', m === mode);
    btn.setAttribute('aria-pressed', String(m === mode));
  }
  page = 0;
  if (mode === 'h') {
    try {
      await loadHype(); // refetch so admin edits show up
    } catch (err) {
      showBanner(`Failed to load hype clips: ${err.message}`, false);
      render();
    }
  } else {
    render();
  }
}
modeBtns.o.addEventListener('click', () => setMode('o'));
modeBtns.d.addEventListener('click', () => setMode('d'));
modeBtns.h.addEventListener('click', () => setMode('h'));

/* ---------------- WebSocket wiring ---------------- */

BB.on('play', (msg) => {
  markPlaying({ type: msg.type, player_id: msg.player_id, clip_id: msg.clip_id });
  hideBanner();
});
BB.on('stop', () => markPlaying(null));
BB.on('state', (msg) => {
  markPlaying(msg.status === 'playing'
    ? { type: msg.type, player_id: msg.player_id, clip_id: msg.clip_id }
    : null);
  if (msg.audio_warning) showBanner(msg.audio_warning);
});
BB.on('warning', (msg) => showBanner(msg.message));

/* ---------------- boot ---------------- */

(async () => {
  BB.connect();
  BB.initMockGPIO(document.getElementById('mock-gpio'));
  try {
    await loadTeams();
  } catch (err) {
    showBanner(`Failed to load: ${err.message}`);
  }
})();
