/* BatterBox kiosk grid (index.html).
 * Tap = walk-up clip, long-press 600ms = home-run clip. Contract: docs/API.md.
 */
import { BB } from './ws.js';

const PAGE_SIZE = 15;
const LONG_PRESS_MS = 600;

const gridEl = document.getElementById('grid');
const phoneListEl = document.getElementById('phone-list');
const teamNameEl = document.getElementById('team-name');
const volLabel = document.getElementById('vol-label');
const banner = document.getElementById('warn-banner');
const walter = document.getElementById('walter');
const pagePrev = document.getElementById('page-prev');
const pageNext = document.getElementById('page-next');
const pageIndicator = document.getElementById('page-indicator');

let players = [];
let page = 0;
let playingPlayerId = null;
let bannerTimer = null;

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
    BB.playback.play(player.id, 'walkup')
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
  const num = document.createElement('div');
  num.className = 'jnum';
  num.textContent = `#${player.jersey_number ?? '?'}`;
  el.appendChild(num);
  if (player.id === playingPlayerId) el.classList.add('playing');
  attachPressHandlers(el, player);
  return el;
}

function render() {
  const totalPages = Math.max(1, Math.ceil(players.length / PAGE_SIZE));
  page = Math.min(page, totalPages - 1);
  const slice = players.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  gridEl.textContent = '';
  for (const p of slice) gridEl.appendChild(buildPlayerEl(p, 'tile'));
  for (let i = slice.length; i < PAGE_SIZE; i++) {
    const filler = document.createElement('div');
    filler.className = 'tile empty';
    gridEl.appendChild(filler);
  }

  phoneListEl.textContent = '';
  for (const p of players) phoneListEl.appendChild(buildPlayerEl(p, 'prow'));

  const paged = players.length > PAGE_SIZE;
  pagePrev.hidden = !paged;
  pageNext.hidden = !paged;
  pageIndicator.hidden = !paged;
  pageIndicator.textContent = `${page + 1} / ${totalPages}`;
}

function markPlaying(playerId) {
  playingPlayerId = playerId;
  for (const el of document.querySelectorAll('[data-player-id]')) {
    el.classList.toggle('playing', Number(el.dataset.playerId) === playerId);
  }
  walter.classList.toggle('playing', playerId != null);
}

/* ---------------- data loading ---------------- */

async function loadPlayers(teamId) {
  // absent players stay in the roster (admin) but never appear on the kiosk
  players = (await BB.api(`/api/teams/${teamId}/players`)).filter((p) => !p.absent);
  page = 0;
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
document.getElementById('vol-up').addEventListener('click', () => {
  BB.playback.changeVolume(5).catch((err) => showBanner(err.message, false));
});
document.getElementById('vol-down').addEventListener('click', () => {
  BB.playback.changeVolume(-5).catch((err) => showBanner(err.message, false));
});
pagePrev.addEventListener('click', () => { page = Math.max(0, page - 1); render(); });
pageNext.addEventListener('click', () => {
  page = Math.min(Math.ceil(players.length / PAGE_SIZE) - 1, page + 1);
  render();
});

/* ---------------- WebSocket wiring ---------------- */

BB.on('play', (msg) => { markPlaying(msg.player_id); hideBanner(); });
BB.on('stop', () => markPlaying(null));
BB.on('state', (msg) => {
  volLabel.textContent = msg.volume ?? BB.getVolume();
  markPlaying(msg.status === 'playing' ? msg.player_id : null);
  if (msg.audio_warning) showBanner(msg.audio_warning);
});
BB.on('volume', (msg) => { volLabel.textContent = msg.volume; });
BB.on('warning', (msg) => showBanner(msg.message));

/* ---------------- boot ---------------- */

(async () => {
  BB.connect();
  BB.initMockGPIO(document.getElementById('mock-gpio'));
  volLabel.textContent = BB.getVolume();
  try {
    await loadTeams();
  } catch (err) {
    showBanner(`Failed to load: ${err.message}`);
  }
})();
