/* BatterBox admin (admin.html): teams, roster, photos, clips, touch drag-drop reorder.
 * Contract: docs/API.md. Reorder uses Pointer Events (not HTML5 DnD — broken on touch).
 */
import { BB } from './ws.js';

const banner = document.getElementById('warn-banner');
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
  const kioskDd = document.getElementById('active-team-select');
  const configDd = document.getElementById('config-team-select');
  kioskDd.textContent = '';
  configDd.textContent = '';
  for (const t of teams) {
    const ko = document.createElement('option');
    ko.value = t.id;
    ko.textContent = t.name;
    kioskDd.appendChild(ko);
    const co = document.createElement('option');
    co.value = t.id;
    co.textContent = t.id === activeTeamId ? `${t.name} ★` : t.name;
    configDd.appendChild(co);
  }
  if (activeTeamId != null) kioskDd.value = String(activeTeamId);
  if (selectedTeamId != null) configDd.value = String(selectedTeamId);
  const sel = teams.find((t) => t.id === selectedTeamId);
  playersTeamName.textContent = sel ? sel.name : '—';
}

document.getElementById('config-team-select').addEventListener('change', async (e) => {
  selectedTeamId = Number(e.target.value);
  openPlayerId = null;
  renderTeams();
  await loadPlayers();
});

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
  row.className = 'player-row' + (p.absent ? ' absent' : '');
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
  // No number entered -> show nothing (not #0, not #?).
  const bits = p.jersey_number != null ? [`#${p.jersey_number}`] : [];
  bits.push(p.active_walkup_clip_id ? 'walkup ✓' : 'walkup —');
  bits.push(p.active_homerun_clip_id ? 'homerun ✓' : 'homerun —');
  bits.push(p.active_walkout_clip_id ? 'walkout ✓' : 'walkout —');
  if (p.absent) bits.push('ABSENT');
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
        // Collapse any open detail panel: the drag moves only .player-row
        // elements, so an open panel would be left stranded under the wrong
        // player after the reorder. Removed directly (NOT via renderPlayers,
        // which would rebuild the list and destroy the row mid-drag).
        const det = listEl.querySelector('.player-detail');
        if (det) {
          const owner = listEl.querySelector(
            `.player-row[data-player-id="${det.dataset.forPlayer}"]`
          );
          det.remove();
          openPlayerId = null;
          if (owner) {
            const b = owner.querySelector('.row-btns button');
            if (b) b.textContent = 'Edit';  // was 'Close' while open
          }
        }
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

  // absent toggle — hidden from the kiosk, stays in the roster. Saves instantly.
  const absL = document.createElement('label');
  absL.className = 'absent-toggle';
  const absC = document.createElement('input');
  absC.type = 'checkbox';
  absC.checked = !!p.absent;
  absC.addEventListener('change', async () => {
    try {
      await BB.api(`/api/players/${p.id}`, { method: 'PATCH', body: { absent: absC.checked } });
      await loadPlayers();
      showBanner(absC.checked ? `${p.name} marked absent — hidden from kiosk.` : `${p.name} is back on the kiosk.`, false);
    } catch (err) { showBanner(err.message, false); }
  });
  absL.append(absC, document.createTextNode(' Absent (hidden from kiosk)'));
  det.appendChild(absL);

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
  for (const type of ['walkup', 'homerun', 'walkout']) {
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
    const addLabel = { walkup: 'Walk-up', homerun: 'Home-run', walkout: 'Walk-out' }[type];
    addB.textContent = `+ Add ${addLabel} Clip`;
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

/* ---------------- hype clips ---------------- */

const hypeListEl = document.getElementById('hype-list');

async function loadHype() {
  let clips;
  try {
    clips = await BB.api('/api/hype');
  } catch (err) {
    hypeListEl.textContent = `Failed to load hype clips: ${err.message}`;
    return;
  }
  hypeListEl.textContent = '';
  if (clips.length === 0) {
    const none = document.createElement('div');
    none.style.color = 'var(--dim)';
    none.style.marginBottom = '8px';
    none.textContent = 'No hype clips yet.';
    hypeListEl.appendChild(none);
  }
  for (const c of clips) hypeListEl.appendChild(buildHypeRow(c));
}

function buildHypeRow(c) {
  const row = document.createElement('div');
  row.className = 'clip-row';

  const info = document.createElement('div');
  info.className = 'c-info';
  info.textContent = `${c.title} — ${fmtDur(c.duration_sec)} · trim ${c.trim_start_sec.toFixed(1)}–${c.trim_end_sec.toFixed(1)}s · ${c.source || 'upload'}`;
  row.appendChild(info);

  const playB = document.createElement('button');
  playB.type = 'button';
  playB.textContent = '▶ Test';
  playB.addEventListener('click', () => {
    BB.playback.playHype(c.id).catch((err) => showBanner(err.message, false));
  });
  row.appendChild(playB);

  const editB = document.createElement('button');
  editB.type = 'button';
  editB.textContent = 'Edit';
  editB.title = 'Re-open trim editor';
  editB.addEventListener('click', () => {
    location.href = `edit.html?hype_clip_id=${c.id}`;
  });
  row.appendChild(editB);

  const delB = document.createElement('button');
  delB.type = 'button';
  delB.className = 'btn-danger';
  delB.textContent = 'Delete';
  delB.addEventListener('click', async () => {
    if (!confirm(`Delete hype clip "${c.title}"?`)) return;
    try {
      await BB.api(`/api/hype/${c.id}`, { method: 'DELETE' });
      await loadHype();
    } catch (err) { showBanner(err.message, false); }
  });
  row.appendChild(delB);

  return row;
}

document.getElementById('btn-add-hype').addEventListener('click', () => {
  location.href = 'edit.html?hype=1';
});

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
      body: { name, jersey_number: jerseyOf(jerseyIn.value) },
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

/* ---------------- Wi-Fi hotspot ---------------- */

const wifiStatusEl = document.getElementById('wifi-status');
const wifiSsidEl = document.getElementById('wifi-ssid');
const wifiPassEl = document.getElementById('wifi-password');
let wifiFormTouched = false; // don't clobber typing with the 10s status poll
wifiSsidEl.addEventListener('input', () => { wifiFormTouched = true; });
wifiPassEl.addEventListener('input', () => { wifiFormTouched = true; });

function renderWifi(s) {
  wifiStatusEl.classList.remove('on', 'off');
  if (!s.available) {
    wifiStatusEl.textContent = `Wi-Fi control unavailable: ${s.detail}`;
    wifiStatusEl.classList.add('off');
  } else if (s.mode === 'hotspot') {
    wifiStatusEl.textContent = s.detail; // "Hotspot ON — SSID '…' — join it and open …"
    wifiStatusEl.classList.add('on');
  } else {
    wifiStatusEl.textContent = s.detail; // client mode / offline
    wifiStatusEl.classList.add('off');
  }
}

async function refreshWifi() {
  try {
    const s = await BB.api('/api/wifi/status');
    if (!wifiFormTouched) {
      wifiSsidEl.value = s.ssid ?? '';
      wifiPassEl.value = s.password ?? '';
    }
    renderWifi(s);
  } catch { /* backend older than this feature — leave last state */ }
}

document.getElementById('btn-wifi-save').addEventListener('click', async () => {
  try {
    const s = await BB.api('/api/wifi/settings', {
      method: 'POST',
      body: { ssid: wifiSsidEl.value.trim(), password: wifiPassEl.value },
    });
    wifiFormTouched = false;
    renderWifi(s);
    showBanner('Wi-Fi settings saved.', false);
  } catch (err) { showBanner(err.message, false); }
});

document.getElementById('btn-wifi-start').addEventListener('click', async () => {
  const ssid = wifiSsidEl.value.trim();
  if (!confirm(`The Pi will leave the current Wi-Fi and broadcast '${ssid}'. This device will disconnect — join '${ssid}' and reopen http://batterbox.local. Continue?`)) return;
  try {
    const s = await BB.api('/api/wifi/hotspot', {
      method: 'POST',
      body: { ssid, password: wifiPassEl.value },
    });
    wifiFormTouched = false;
    renderWifi(s);
    showBanner(s.detail, false);
  } catch (err) {
    showBanner(err.message, false);
    refreshWifi();
  }
});

document.getElementById('btn-wifi-stop').addEventListener('click', async () => {
  try {
    const s = await BB.api('/api/wifi/hotspot/off', { method: 'POST' });
    renderWifi(s);
    showBanner(s.detail, false);
  } catch (err) {
    showBanner(err.message, false);
    refreshWifi();
  }
});
document.getElementById('btn-wifi-client').addEventListener('click', async () => {
  const ssid = wifiSsidEl.value.trim();
  if (!confirm(`The Pi will join '${ssid}' as a client (the hotspot, if on, will stop). This device will disconnect unless it's also on '${ssid}' — reopen http://batterbox.local there. Continue?`)) return;
  try {
    const s = await BB.api('/api/wifi/client', {
      method: 'POST',
      body: { ssid, password: wifiPassEl.value },
    });
    wifiFormTouched = false;
    renderWifi(s);
    showBanner(s.detail, false);
  } catch (err) {
    showBanner(err.message, false);
    refreshWifi();
  }
});
setInterval(refreshWifi, 10000);

/* ---------------- WebSocket (volume sync for mock GPIO) ---------------- */

BB.on('warning', (msg) => showBanner(msg.message, false));

/* ---------------- boot ---------------- */

(async () => {
  BB.connect();
  refreshBt();
  refreshWifi();
  try {
    await loadTeams();
    await loadPlayers();
    await loadHype();
  } catch (err) {
    showBanner(`Failed to load: ${err.message}`);
  }
})();
