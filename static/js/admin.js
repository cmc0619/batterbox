/* BatterBox admin (admin.html): teams, roster, photos, clips, touch drag-drop reorder.
 * Contract: docs/API.md. Reorder uses Pointer Events (not HTML5 DnD — broken on touch).
 */
import { BB } from './ws.js';

const banner = document.getElementById('warn-banner');
const chipsEl = document.getElementById('team-chips');
const listEl = document.getElementById('player-list');
const playersTeamName = document.getElementById('players-team-name');

let teams = [];
let activeTeamId = null;
let selectedTeamId = null;
let players = [];
let openPlayerId = null;

/* ---------------- helpers ---------------- */

let bannerTimer = null;
function showBanner(msg, sticky = true) {
  banner.textContent = msg;
  banner.classList.add('show');
  if (bannerTimer) clearTimeout(bannerTimer);
  bannerTimer = null;
  if (!sticky) bannerTimer = setTimeout(() => banner.classList.remove('show'), 5000);
}
function hideBanner() { banner.classList.remove('show'); }

function jerseyOf(input) {
  const v = String(input).trim();
  if (v === '') return null; // backend takes int|null; '' would 422 the whole save
  const n = parseInt(v, 10);
  return Number.isNaN(n) ? v : n;
}

function jerseyPlaceholder(player) {
  const d = document.createElement('div');
  d.className = 'jersey-ph';
  d.textContent = player.jersey_number ?? '?';
  return d;
}
function makeThumb(player) {
  if (player.photo_url) {
    const img = document.createElement('img');
    img.className = 'p-thumb';
    img.src = player.photo_url;
    img.alt = '';
    img.draggable = false;
    img.addEventListener('error', () => img.replaceWith(jerseyPlaceholder(player)), { once: true });
    return img;
  }
  return jerseyPlaceholder(player);
}

function fmtDur(sec) {
  if (sec == null) return '?';
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/* ---------------- teams ---------------- */

function renderTeams() {
  chipsEl.textContent = '';
  for (const t of teams) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'team-chip' + (t.id === selectedTeamId ? ' selected' : '');
    b.textContent = t.name;
    if (t.id === activeTeamId) {
      const star = document.createElement('span');
      star.className = 'active-star';
      star.textContent = ' ★';
      star.title = 'Active team';
      b.appendChild(star);
    }
    b.addEventListener('click', async () => {
      selectedTeamId = t.id;
      openPlayerId = null;
      renderTeams();
      await loadPlayers();
    });
    chipsEl.appendChild(b);
  }
  const sel = teams.find((t) => t.id === selectedTeamId);
  playersTeamName.textContent = sel ? sel.name : '—';
  // kiosk active-team dropdown
  const dd = document.getElementById('active-team-select');
  dd.textContent = '';
  for (const t of teams) {
    const opt = document.createElement('option');
    opt.value = t.id;
    opt.textContent = t.name;
    dd.appendChild(opt);
  }
  if (activeTeamId != null) dd.value = String(activeTeamId);
}

document.getElementById('active-team-select').addEventListener('change', async (e) => {
  const id = Number(e.target.value);
  try {
    await BB.api('/api/teams/active', { method: 'POST', body: { team_id: id } });
    activeTeamId = id;
    renderTeams();
    showBanner('Kiosk team saved — back to KIOSK to see it.', false);
  } catch (err) { showBanner(err.message, false); }
});

async function loadTeams() {
  const [ts, active] = await Promise.all([
    BB.api('/api/teams'),
    BB.api('/api/teams/active'),
  ]);
  teams = ts;
  activeTeamId = active.team_id;
  if (!teams.some((t) => t.id === selectedTeamId)) {
    selectedTeamId = teams.some((t) => t.id === activeTeamId)
      ? activeTeamId
      : (teams[0] && teams[0].id);
  }
  renderTeams();
}

document.getElementById('btn-add-team').addEventListener('click', async () => {
  const input = document.getElementById('new-team-name');
  const name = input.value.trim();
  if (!name) return;
  try {
    const t = await BB.api('/api/teams', { method: 'POST', body: { name } });
    input.value = '';
    selectedTeamId = t.id;
    openPlayerId = null;
    await loadTeams();
    await loadPlayers();
  } catch (err) { showBanner(err.message, false); }
});

document.getElementById('btn-rename-team').addEventListener('click', async () => {
  const t = teams.find((x) => x.id === selectedTeamId);
  if (!t) return;
  const name = prompt('New team name:', t.name);
  if (!name || !name.trim()) return;
  try {
    await BB.api(`/api/teams/${t.id}`, { method: 'PATCH', body: { name: name.trim() } });
    await loadTeams();
  } catch (err) { showBanner(err.message, false); }
});

document.getElementById('btn-delete-team').addEventListener('click', async () => {
  const t = teams.find((x) => x.id === selectedTeamId);
  if (!t) return;
  if (!confirm(`Delete team "${t.name}" and ALL its players and clips?`)) return;
  try {
    await BB.api(`/api/teams/${t.id}`, { method: 'DELETE' });
    selectedTeamId = null;
    openPlayerId = null;
    await loadTeams();
    await loadPlayers();
  } catch (err) { showBanner(err.message, false); }
});

/* ---------------- players ---------------- */

async function loadPlayers() {
  listEl.textContent = '';
  if (selectedTeamId == null) { players = []; return; }
  players = await BB.api(`/api/teams/${selectedTeamId}/players`);
  renderPlayers();
}

function renderPlayers() {
  listEl.textContent = '';
  for (const p of players) {
    listEl.appendChild(buildPlayerRow(p));
    if (p.id === openPlayerId) listEl.appendChild(buildDetail(p));
  }
}

function buildPlayerRow(p) {
  const row = document.createElement('div');
  row.className = 'player-row';
  row.dataset.playerId = p.id;

  const handle = document.createElement('div');
  handle.className = 'drag-handle';
  handle.textContent = '≡';
  handle.title = 'Drag to reorder';
  row.appendChild(handle);

  row.appendChild(makeThumb(p));

  const info = document.createElement('div');
  info.className = 'p-info';
  const nm = document.createElement('div');
  nm.className = 'p-name';
  nm.textContent = p.name;
  const sub = document.createElement('div');
  sub.className = 'p-sub';
  const bits = [`#${p.jersey_number ?? '?'}`];
  bits.push(p.active_walkup_clip_id ? 'walkup ✓' : 'walkup —');
  bits.push(p.active_homerun_clip_id ? 'homerun ✓' : 'homerun —');
  sub.textContent = bits.join(' · ');
  info.appendChild(nm);
  info.appendChild(sub);
  row.appendChild(info);

  const btns = document.createElement('div');
  btns.className = 'row-btns';
  const editB = document.createElement('button');
  editB.type = 'button';
  editB.textContent = p.id === openPlayerId ? 'Close' : 'Edit';
  editB.addEventListener('click', (e) => {
    e.stopPropagation();
    openPlayerId = openPlayerId === p.id ? null : p.id;
    renderPlayers();
  });
  btns.appendChild(editB);
  row.appendChild(btns);

  info.addEventListener('click', () => {
    openPlayerId = openPlayerId === p.id ? null : p.id;
    renderPlayers();
  });

  attachDrag(row, handle);
  return row;
}

/* ---------------- pointer-based drag reorder ---------------- */

function attachDrag(row, handle) {
  handle.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    // NOTE: no setPointerCapture — Chrome releases capture when the row is
    // reparented by insertBefore mid-drag, which silently killed the drag.
    // Window-level listeners survive DOM moves; touch-action:none on the
    // handle prevents scroll takeover.
    const startY = e.clientY;
    const grabTop = row.offsetTop;
    let dragging = false;
    let moved = false;

    const clearIndicators = () => {
      for (const r of listEl.querySelectorAll('.player-row')) r.classList.remove('drop-after');
    };

    const onMove = (ev) => {
      const dy = ev.clientY - startY;
      if (!dragging) {
        if (Math.abs(dy) < 8) return;
        dragging = true;
        row.classList.add('dragging');
      }
      const visualTop = grabTop + dy;
      row.style.transform = `translateY(${visualTop - row.offsetTop}px)`;

      // live reorder: count siblings whose midpoint is above the dragged center
      const rows = [...listEl.querySelectorAll('.player-row')];
      const center = visualTop + row.offsetHeight / 2;
      let insertAt = 0;
      for (const r of rows) {
        if (r === row) continue;
        if (center > r.offsetTop + r.offsetHeight / 2) insertAt++;
      }
      const currentIdx = rows.indexOf(row);
      if (insertAt !== currentIdx) {
        moved = true;
        const ref = rows.filter((r) => r !== row)[insertAt] || null;
        listEl.insertBefore(row, ref);
        row.style.transform = `translateY(${visualTop - row.offsetTop}px)`;
      }
      clearIndicators();
      const prev = row.previousElementSibling;
      if (prev && prev.classList.contains('player-row')) prev.classList.add('drop-after');
    };

    const finish = async () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
      row.classList.remove('dragging');
      row.style.transform = '';
      clearIndicators();
      if (!dragging || !moved) return;
      const ids = [...listEl.querySelectorAll('.player-row')].map((r) => Number(r.dataset.playerId));
      try {
        await BB.api(`/api/teams/${selectedTeamId}/players/reorder`, {
          method: 'POST',
          body: { player_ids: ids },
        });
        players.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
      } catch (err) {
        showBanner(`Reorder failed: ${err.message}`, false);
        await loadPlayers();
      }
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
  });
}

/* ---------------- player detail (edit / photo / clips) ---------------- */

function buildDetail(p) {
  const det = document.createElement('div');
  det.className = 'player-detail';
  det.dataset.forPlayer = p.id;

  // name / jersey
  const nl = document.createElement('label'); nl.textContent = 'Name';
  const ni = document.createElement('input'); ni.value = p.name;
  const jl = document.createElement('label'); jl.textContent = 'Jersey number';
  const ji = document.createElement('input'); ji.value = p.jersey_number ?? ''; ji.inputMode = 'numeric';
  det.append(nl, ni, jl, ji);

  const row1 = document.createElement('div');
  row1.className = 'form-row';
  const saveB = document.createElement('button');
  saveB.type = 'button'; saveB.className = 'btn-primary'; saveB.textContent = 'Save';
  saveB.addEventListener('click', async () => {
    try {
      await BB.api(`/api/players/${p.id}`, {
        method: 'PATCH',
        body: { name: ni.value.trim() || p.name, jersey_number: jerseyOf(ji.value) },
      });
      await loadPlayers();
    } catch (err) { showBanner(err.message, false); }
  });
  const delB = document.createElement('button');
  delB.type = 'button'; delB.className = 'btn-danger'; delB.textContent = 'Delete Player';
  delB.addEventListener('click', async () => {
    if (!confirm(`Delete ${p.name} and all their clips?`)) return;
    try {
      await BB.api(`/api/players/${p.id}`, { method: 'DELETE' });
      openPlayerId = null;
      await loadPlayers();
    } catch (err) { showBanner(err.message, false); }
  });
  row1.append(saveB, delB);
  det.appendChild(row1);

  // photo
  const pl = document.createElement('label'); pl.textContent = 'Photo (jpg/png, ≤5MB)';
  const fileIn = document.createElement('input');
  fileIn.type = 'file';
  fileIn.accept = 'image/jpeg,image/png';
  fileIn.addEventListener('change', async () => {
    const f = fileIn.files && fileIn.files[0];
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) { showBanner('Photo must be ≤5MB', false); return; }
    const fd = new FormData();
    fd.append('file', f);
    try {
      await BB.api(`/api/players/${p.id}/photo`, { method: 'POST', formData: fd });
      await loadPlayers();
    } catch (err) { showBanner(err.message, false); }
  });
  det.append(pl, fileIn);

  // clips
  const clipsBox = document.createElement('div');
  clipsBox.textContent = 'Loading clips…';
  det.appendChild(clipsBox);
  loadClips(p, clipsBox);

  return det;
}

async function loadClips(p, box) {
  let clips;
  try {
    clips = await BB.api(`/api/players/${p.id}/clips`);
  } catch (err) {
    box.textContent = `Failed to load clips: ${err.message}`;
    return;
  }
  box.textContent = '';
  for (const type of ['walkup', 'homerun']) {
    const group = document.createElement('div');
    group.className = 'clip-group';
    const h = document.createElement('h3');
    const tag = document.createElement('span');
    tag.className = `tag ${type}`;
    tag.textContent = type.toUpperCase();
    h.appendChild(tag);
    group.appendChild(h);

    const ofType = clips.filter((c) => c.type === type);
    if (ofType.length === 0) {
      const none = document.createElement('div');
      none.style.color = 'var(--dim)';
      none.textContent = 'No clips yet.';
      group.appendChild(none);
    }
    for (const c of ofType) group.appendChild(buildClipRow(p, c));

    const addB = document.createElement('button');
    addB.type = 'button';
    addB.className = 'btn-primary';
    addB.style.minHeight = '60px';
    addB.style.fontSize = '20px';
    addB.textContent = `+ Add ${type === 'walkup' ? 'Walk-up' : 'Home-run'} Clip`;
    addB.addEventListener('click', () => {
      location.href = `edit.html?player_id=${p.id}&type=${type}`;
    });
    group.appendChild(addB);
    box.appendChild(group);
  }
}

function buildClipRow(p, c) {
  const row = document.createElement('div');
  row.className = 'clip-row';

  const info = document.createElement('div');
  info.className = 'c-info';
  info.textContent = `${fmtDur(c.duration_sec)} · trim ${c.trim_start_sec.toFixed(1)}–${c.trim_end_sec.toFixed(1)}s · ${c.source}`;
  if (c.is_active) {
    const tag = document.createElement('span');
    tag.className = 'tag active';
    tag.textContent = 'ACTIVE';
    info.appendChild(document.createTextNode(' '));
    info.appendChild(tag);
  }
  row.appendChild(info);

  const playB = document.createElement('button');
  playB.type = 'button';
  playB.textContent = '▶ Test';
  playB.addEventListener('click', () => {
    BB.playback.playClip(c.id).catch((err) => showBanner(err.message, false));
  });
  row.appendChild(playB);

  const editB = document.createElement('button');
  editB.type = 'button';
  editB.textContent = 'Edit';
  editB.title = 'Re-open trim editor';
  editB.addEventListener('click', () => {
    location.href = `edit.html?clip_id=${c.id}`;
  });
  row.appendChild(editB);

  if (!c.is_active) {
    const actB = document.createElement('button');
    actB.type = 'button';
    actB.className = 'btn-ok';
    actB.textContent = 'Activate';
    actB.addEventListener('click', async () => {
      try {
        await BB.api(`/api/clips/${c.id}/activate`, { method: 'POST' });
        await loadPlayers(); // reloads roster + reopens detail
      } catch (err) { showBanner(err.message, false); }
    });
    row.appendChild(actB);
  }

  const delB = document.createElement('button');
  delB.type = 'button';
  delB.className = 'btn-danger';
  delB.textContent = 'Delete';
  delB.addEventListener('click', async () => {
    if (!confirm('Delete this clip?')) return;
    try {
      await BB.api(`/api/clips/${c.id}`, { method: 'DELETE' });
      await loadPlayers();
    } catch (err) { showBanner(err.message, false); }
  });
  row.appendChild(delB);

  return row;
}

/* ---------------- add player ---------------- */

document.getElementById('btn-add-player').addEventListener('click', async () => {
  if (selectedTeamId == null) { showBanner('Create a team first.', false); return; }
  const nameIn = document.getElementById('new-player-name');
  const jerseyIn = document.getElementById('new-player-jersey');
  const name = nameIn.value.trim();
  if (!name) return;
  try {
    await BB.api(`/api/teams/${selectedTeamId}/players`, {
      method: 'POST',
      body: { name, jersey_number: jerseyOf(jerseyIn.value || '0') },
    });
    nameIn.value = '';
    jerseyIn.value = '';
    await loadPlayers();
  } catch (err) { showBanner(err.message, false); }
});

/* ---------------- Bluetooth speaker pairing ---------------- */

const btBtn = document.getElementById('btn-bt');
let btStatus = { available: false, pairing: false, detail: '', devices: [] };

function renderBt() {
  const connected = (btStatus.devices || []).find((d) => d.connected);
  btBtn.classList.toggle('pairing', !!btStatus.pairing);
  btBtn.classList.toggle('connected', !btStatus.pairing && !!connected);
  const hint = btStatus.pairing
    ? 'Pairing… tap to stop'
    : connected
      ? `Connected: ${connected.name}`
      : (btStatus.detail || 'Bluetooth');
  btBtn.title = hint;
  btBtn.setAttribute('aria-label', `Bluetooth — ${hint}`);
}

async function refreshBt() {
  try {
    btStatus = await BB.api('/api/bluetooth/status');
  } catch { /* backend older than this feature — leave last state */ }
  renderBt();
}

btBtn.addEventListener('click', async () => {
  try {
    await refreshBt();
    if (!btStatus.available) {
      showBanner(`Bluetooth unavailable: ${btStatus.detail}`, false);
      return;
    }
    btStatus = btStatus.pairing
      ? await BB.api('/api/bluetooth/pairing/stop', { method: 'POST' })
      : await BB.api('/api/bluetooth/pairing', { method: 'POST', body: { duration_sec: 120 } });
    renderBt();
  } catch (err) {
    showBanner(err.message, false);
    refreshBt();
  }
});
setInterval(refreshBt, 5000);

/* ---------------- WebSocket (volume sync for mock GPIO) ---------------- */

BB.on('warning', (msg) => showBanner(msg.message, false));

/* ---------------- boot ---------------- */

(async () => {
  BB.connect();
  BB.initMockGPIO(document.getElementById('mock-gpio'));
  refreshBt();
  try {
    await loadTeams();
    await loadPlayers();
  } catch (err) {
    showBanner(`Failed to load: ${err.message}`);
  }
})();
