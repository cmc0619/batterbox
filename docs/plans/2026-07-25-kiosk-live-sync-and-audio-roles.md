# Kiosk Live Data Sync + Client Audio Roles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Push a `data_changed` WebSocket event on every kiosk-relevant REST mutation so open kiosks refresh live; (2) add an explicit client audio role so exactly one device (the Pi kiosk) plays sound while phones/admin tabs stay silent controllers.

**Architecture:** Server-side, a tiny `notify_data_changed(scope)` helper in `app/services/audio.py` (where `ws_manager` already lives) is called from the mutating router endpoints; it broadcasts `{"event": "data_changed", "scope": ...}` with no payload — clients refetch via REST. Client-side, `grid.js` debounces the event into a roster/team reload (and refreshes after WS reconnect), and `ws.js` gains a player/controller role: only the player role touches the `Audio` element or reports `ended`. The Pi kiosk launcher opens `/?player=1`; a top-bar speaker toggle lets any device claim/release the role.

**Tech Stack:** FastAPI + existing `WSManager` broadcast (server), vanilla ES-module JS (no build step), Chromium kiosk.

## Background (validated findings)

- **Finding 1 (validated):** `static/js/grid.js` loads teams/players once in its boot IIFE (`loadTeams()`); the WS contract (`docs/API.md`) carries only `play`/`stop`/`volume`/`warning`/`state`. No router broadcasts on data mutations. So a phone changing the active team (`POST /api/teams/active`) updates the server — and GPIO **NEXT** (`audio.play_next()` reads `db.get_active_team_id()` live) — while the touchscreen keeps rendering the old roster.
- **Finding 2 (validated):** `static/js/ws.js` owns a module-level `new Audio()` and `handlePlay()` unconditionally sets `audio.src` and plays for **every** connected client; `admin.js` also calls `BB.connect()`, and `editor.js` imports the same module. Every open page plays every song (echo), and each client's `ended` handler posts `/api/playback/stop` (the `play_id` guard only filters *stale* stops, not the earliest same-play stop).

## Global Constraints

- **CODE FREEZE:** `app/**` and `static/**` may only be changed with the owner's explicit prior approval. This plan IS the approval request — do not start Task 1 until the owner has approved.
- `docs/API.md` is the **binding contract** — it must change **in the same commit** as any API/WS change.
- No test suite exists; the repo convention is scripted/manual verification against acceptance criteria (see per-task verification steps). Do not introduce pytest.
- Kiosk UI rules: exactly 1024×600, no text below ~18px, huge touch targets, no hover-only interaction.
- Cloud VM run command: `DATA_DIR=./data MOCK_GPIO=true .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080` (never Docker in the cloud VM; `./data` is gitignored, never commit it).
- Commit + push after each verified slice; keep `AGENTS.md` and `PROGRESS.md` current in the same commits.
- PRs are always **ready for review**, never draft.
- Branch: `cursor/kiosk-live-sync-and-audio-roles-d561`.

---

### Task 1: Server — broadcast `data_changed` on kiosk-relevant mutations

**Files:**
- Modify: `app/services/audio.py` (add helper after `ws_manager = WSManager()`, ~line 54)
- Modify: `app/routers/teams.py`
- Modify: `app/routers/players.py`
- Modify: `app/routers/clips.py`
- Modify: `app/routers/hype.py`
- Modify: `docs/API.md` (WebSocket section, same commit)

**Interfaces:**
- Produces: `audio.notify_data_changed(scope: str) -> None` broadcasting `{"event": "data_changed", "scope": "teams"|"players"|"hype"}`. Task 2 consumes the WS message shape.

**Scope semantics (lock these in):**
- `"teams"` — team list or active team changed: `POST /api/teams`, `PATCH /api/teams/{id}`, `DELETE /api/teams/{id}`, `POST /api/teams/active`.
- `"players"` — anything the kiosk roster render depends on: player create/update/delete/reorder/photo, **and** clip create/activate/delete (they change `active_*_clip_id`, which drives D-mode visibility). `PATCH /api/clips/{id}` is deliberately excluded — a re-render changes nothing the kiosk displays.
- `"hype"` — hype clip created or deleted (`POST /api/hype`, `DELETE /api/hype/{id}`). `PATCH /api/hype/{id}` excluded for the same reason (title is immutable).
- Settings/Bluetooth/Wi-Fi mutations: no broadcast (nothing on the kiosk grid reads them live).

- [ ] **Step 1: Add the helper to `app/services/audio.py`** directly below `ws_manager = WSManager()`:

```python
def notify_data_changed(scope: str) -> None:
    """Broadcast that kiosk-relevant data changed. No payload — clients
    refetch what they display via REST. scope per docs/API.md:
    "teams" | "players" | "hype"."""
    ws_manager.broadcast({"event": "data_changed", "scope": scope})
```

- [ ] **Step 2: Instrument `app/routers/teams.py`.** Add `from ..services import audio` to the imports, then notify after each successful mutation (never on the 404 paths):

```python
@router.post("/active")
def set_active_team(body: ActiveTeamSet):
    if db.get_team(body.team_id) is None:
        raise HTTPException(404, f"team {body.team_id} not found")
    db.set_active_team_id(body.team_id)
    audio.notify_data_changed("teams")
    return {"team_id": body.team_id}


@router.post("", status_code=201)
def create_team(body: TeamCreate):
    team = db.create_team(body.name)
    audio.notify_data_changed("teams")
    return team


@router.patch("/{team_id}")
def update_team(team_id: int, body: TeamUpdate):
    team = db.update_team(team_id, body.name)
    if team is None:
        raise HTTPException(404, f"team {team_id} not found")
    audio.notify_data_changed("teams")
    return team


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: int):
    if not db.delete_team(team_id):
        raise HTTPException(404, f"team {team_id} not found")
    audio.notify_data_changed("teams")
    return Response(status_code=204)
```

- [ ] **Step 3: Instrument `app/routers/players.py`.** Add `from ..services import audio` to the imports. Call `audio.notify_data_changed("players")`:
  - `create_player`: capture `player = db.create_player(...)`, notify, `return player`.
  - `update_player`: capture `player = db.update_player(...)`, notify, `return player`.
  - `delete_player`: after the `if not db.delete_player(...)` guard, before `return`.
  - `reorder_players`: after `db.reorder_players(...)`, before `return`.
  - `upload_photo`: after `db.set_player_photo(player_id, photo_url)` (put it right after that line, before the old-photo cleanup — a cleanup failure shouldn't suppress the refresh).

- [ ] **Step 4: Instrument `app/routers/clips.py`.** Add `from ..services import audio` to the imports (keep the existing `from ..services import clipper`). Notify `"players"`:
  - `create_clip`: capture the result instead of returning inline —

```python
    try:
        clip = clipper.create_clip(
            job_id=body.job_id,
            player_id=body.player_id,
            clip_type=body.type,
            trim_start_sec=body.trim_start_sec,
            trim_end_sec=body.trim_end_sec,
            fade_in_ms=body.fade_in_ms,
            fade_out_ms=body.fade_out_ms,
            volume_boost_db=body.volume_boost_db,
        )
    except clipper.JobError as e:
        raise HTTPException(400, str(e)) from e
    except clipper.RenderError as e:
        raise HTTPException(500, str(e)) from e
    audio.notify_data_changed("players")
    return clip
```

  - `activate_clip`: after `db.activate_clip(clip_id)`, before `return db.get_clip(clip_id)`.
  - `delete_clip`: after the `if not db.delete_clip(...)` guard, before `return`.
  - Do **not** touch `patch_clip`, imports/jobs endpoints, or `edit_context`.

- [ ] **Step 5: Instrument `app/routers/hype.py`.** Add `from ..services import audio`. Notify `"hype"` in `create_hype` (capture result → notify → return, same pattern as `create_clip`) and `delete_hype` (after the guard). Do not touch `patch_hype`.

- [ ] **Step 6: Update `docs/API.md` WebSocket section** (same commit). Add to the message examples block:

```json
{ "event": "data_changed", "scope": "teams" }
```

and after the `type` semantics paragraph add:

> `data_changed` fires after any REST mutation of kiosk-relevant data — scope `teams` (team created/renamed/deleted or active team changed), `players` (player create/update/delete/reorder/photo, and clip create/activate/delete — those change `active_*_clip_id`), `hype` (hype clip created/deleted). It carries no payload; clients refetch what they display via REST. The kiosk refreshes its grid on this event (debounced ~300ms) and after a WS reconnect (changes made while disconnected would otherwise be missed).

- [ ] **Step 7: Verify with a WS listener + curl.** Start the app (`DATA_DIR=./data MOCK_GPIO=true .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080`, backgrounded), then:

```bash
.venv/bin/python - <<'EOF' > /tmp/ws-events.log 2>&1 &
import asyncio, websockets
async def main():
    async with websockets.connect("ws://localhost:8080/ws") as ws:
        while True:
            print(await ws.recv(), flush=True)
asyncio.run(main())
EOF
sleep 1
curl -s -X POST localhost:8080/api/teams/active -H 'Content-Type: application/json' -d '{"team_id": 2}'
curl -s -X PATCH localhost:8080/api/players/1 -H 'Content-Type: application/json' -d '{"absent": true}'
curl -s -X PATCH localhost:8080/api/players/1 -H 'Content-Type: application/json' -d '{"absent": false}'
curl -s -X POST localhost:8080/api/teams/active -H 'Content-Type: application/json' -d '{"team_id": 1}'
sleep 1
cat /tmp/ws-events.log
```

Expected: the initial `state` message, then `{"event": "data_changed", "scope": "teams"}`, two `{"event": "data_changed", "scope": "players"}`, and a final `teams`. Also confirm a 404 mutation (e.g. `curl -X PATCH localhost:8080/api/players/99999 ...`) emits **nothing**. Kill the listener when done.

- [ ] **Step 8: Commit**

```bash
git add app/services/audio.py app/routers/teams.py app/routers/players.py app/routers/clips.py app/routers/hype.py docs/API.md
git commit -m "Broadcast data_changed over /ws on kiosk-relevant mutations"
git push -u origin cursor/kiosk-live-sync-and-audio-roles-d561
```

---

### Task 2: Kiosk — refresh grid on `data_changed` and on WS reconnect

**Files:**
- Modify: `static/js/grid.js`

**Interfaces:**
- Consumes: WS message `{ event: "data_changed", scope: "teams"|"players"|"hype" }` from Task 1, and the existing `BB.on('open', ...)` event `ws.js` already emits on every (re)connect.

- [ ] **Step 1: Make refreshes page-preserving.** Replace `loadPlayers` and `loadTeams` in `static/js/grid.js` with:

```js
let currentTeamId = null;

async function loadPlayers(teamId, { keepPage = false } = {}) {
  // absent players stay in the roster (admin) but never appear on the kiosk
  players = (await BB.api(`/api/teams/${teamId}/players`)).filter((p) => !p.absent);
  if (!keepPage) page = 0; // render() clamps a kept page if the list shrank
  render();
}

async function loadTeams({ keepPage = false } = {}) {
  const [teams, active] = await Promise.all([
    BB.api('/api/teams'),
    BB.api('/api/teams/active'),
  ]);
  const selected = teams.some((t) => t.id === active.team_id)
    ? active.team_id
    : (teams[0] && teams[0].id);
  if (selected == null) {
    currentTeamId = null;
    players = [];
    render();
    showBanner('No teams yet — open ADMIN to create one.');
    return;
  }
  const teamChanged = selected !== currentTeamId;
  currentTeamId = selected;
  const team = teams.find((t) => t.id === selected);
  teamNameEl.textContent = team ? team.name : 'BatterBox';
  // A different team is a fresh grid — always back to page 1.
  await loadPlayers(selected, { keepPage: keepPage && !teamChanged });
}
```

- [ ] **Step 2: Wire the WS events.** In the "WebSocket wiring" section of `grid.js` (after the existing `BB.on('warning', ...)` line) add:

```js
// Remote admin edits (phone) must reach an open kiosk without a reload.
// Debounce: a drag-reorder or multi-field save fires several mutations
// back-to-back; one refetch after the burst is enough.
let refreshTimer = null;
function scheduleRosterRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    loadTeams({ keepPage: true })
      .catch((err) => showBanner(`Refresh failed: ${err.message}`, false));
  }, 300);
}

BB.on('data_changed', (msg) => {
  if (msg.scope === 'hype') {
    // Entering H mode refetches anyway (setMode); refresh live only when
    // hype tiles are currently on screen.
    if (mode === 'h') {
      loadHype().catch((err) => showBanner(`Refresh failed: ${err.message}`, false));
    }
    return;
  }
  scheduleRosterRefresh(); // 'teams' and 'players' both re-render the roster
});

// Changes made while the socket was down never produced an event — refetch
// on every reconnect. The first open is boot; the boot IIFE already loads.
let firstOpen = true;
BB.on('open', () => {
  if (firstOpen) { firstOpen = false; return; }
  scheduleRosterRefresh();
});
```

- [ ] **Step 3: Verify live refresh end-to-end.** With the app running, launch a headless kiosk page and drive it over CDP (pattern from the 2026-07-21 drag-bug lesson). Requires a Chromium binary (`chromium`, `chromium-browser`, or `google-chrome`; on the cloud VM `sudo apt-get install -y chromium` if missing):

```bash
chromium --headless=new --remote-debugging-port=9222 --no-sandbox \
  --autoplay-policy=no-user-gesture-required http://localhost:8080/ &
sleep 3
.venv/bin/python - <<'EOF'
import asyncio, json, urllib.request, websockets

async def evaljs(ws, expr, _id=[0]):
    _id[0] += 1
    await ws.send(json.dumps({"id": _id[0], "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == _id[0]:
            return msg["result"]["result"].get("value")

async def main():
    tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
    url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
    async with websockets.connect(url, max_size=None) as ws:
        before = await evaljs(ws, "document.getElementById('team-name').textContent")
        import subprocess
        subprocess.run(["curl", "-s", "-X", "PATCH", "localhost:8080/api/teams/1",
            "-H", "Content-Type: application/json", "-d", '{"name": "Renamed Live"}'])
        await asyncio.sleep(1.5)
        after = await evaljs(ws, "document.getElementById('team-name').textContent")
        tiles = await evaljs(ws, "document.querySelectorAll('#grid [data-player-id]').length")
        print("before:", before, "| after:", after, "| tiles:", tiles)
        assert after == "Renamed Live", "kiosk did not refresh"

asyncio.run(main())
EOF
```

Expected: `after: Renamed Live` with no reload. Then rename the team back (`curl -X PATCH ... -d '{"name": "Sandlot Sluggers"}'` — use the original seeded name). Also verify the active-team case: `POST /api/teams/active` with the other team id and confirm `team-name` and the tile count change within ~2s, then switch back. Kill the headless Chromium afterwards. (Fallback without Chromium: two normal browser tabs — edit in admin, watch the kiosk tab update.)

- [ ] **Step 4: Commit**

```bash
git add static/js/grid.js
git commit -m "Kiosk: live grid refresh on data_changed and WS reconnect"
git push
```

---

### Task 3: Client audio roles — only the designated player device makes sound

**Files:**
- Modify: `static/js/ws.js`
- Modify: `static/index.html` (top bar)
- Modify: `static/js/grid.js` (toggle wiring)
- Modify: `static/css/batterbox.css`
- Modify: `docs/API.md` (WS "Browser playback backend" paragraph, same commit)

**Interfaces:**
- Produces: `BB.isAudioPlayer(): boolean`, `BB.setAudioPlayer(v: boolean)`, and a `BB.on('audiorole', ({ player }) => ...)` event. Role sources, highest precedence first: localStorage key `bb-audio-player` (`'1'`/`'0'`, written only by the toggle), then URL param `?player=1`, else controller (silent).
- Consumes: nothing new from the server — the role is purely client-side; the WS contract is unchanged except for documentation.

**Design notes (why this shape):**
- Default **controller** so a forgotten tab can never join the PA. The Pi kiosk runs `--incognito` (no localStorage persistence), so its role must come from the launcher URL param — that's Task 4.
- Only the player role reports `ended` → the "earliest-finishing device stops playback for the others" failure disappears with the echo.
- Known trade-off (accepted): with `AUDIO_BACKEND=browser` and **no** player-role client connected, a play request goes silent and the state sticks at "playing" until STOP (no client fires `ended`). The muted-speaker toggle on the kiosk makes this visible and fixable in one tap; `AUDIO_BACKEND=server` (mpv) remains the headless alternative.

- [ ] **Step 1: Add the role to `static/js/ws.js`.** Insert between the "event bus" and "audio playback" sections:

```js
/* ---------------- audio role ----------------
 * 'player' = this device renders the sound (the Pi kiosk); everything else
 * is a 'controller' — sends commands, mirrors state, stays silent. Default
 * is controller so a forgotten phone/admin tab can never join the PA.
 * The kiosk launcher opens /?player=1; the kiosk top-bar speaker toggle
 * overrides via localStorage (the Pi's incognito Chromium never persists
 * it, so the URL param stays authoritative there).
 */
const AUDIO_ROLE_KEY = 'bb-audio-player';

function detectAudioRole() {
  let stored = null;
  try { stored = localStorage.getItem(AUDIO_ROLE_KEY); } catch { /* blocked */ }
  if (stored === '1') return true;
  if (stored === '0') return false;
  return new URLSearchParams(location.search).get('player') === '1';
}

let isPlayer = detectAudioRole();

function setAudioPlayer(v) {
  isPlayer = !!v;
  try { localStorage.setItem(AUDIO_ROLE_KEY, isPlayer ? '1' : '0'); } catch { /* blocked */ }
  if (!isPlayer) {
    audio.pause();
    try { audio.currentTime = 0; } catch { /* not loaded yet */ }
  }
  emit('audiorole', { player: isPlayer });
}
```

- [ ] **Step 2: Guard playback in `ws.js`.** In `handlePlay`, keep all state bookkeeping unconditional and gate only the audio work — after the `lastState = { ... }` assignment insert:

```js
  if (!isPlayer) return; // controllers mirror state but never play audio
```

(everything from `audio.volume = vol / 100;` down stays player-only). Leave `handleStop`, `handleVolume`, `handleState`, and the `ended` listener untouched — a controller's `Audio` element never plays, so `pause()` is a no-op and `ended` never fires.

- [ ] **Step 3: Export the role API.** Extend the `BB` export object in `ws.js`:

```js
  isAudioPlayer: () => isPlayer,
  setAudioPlayer,
```

- [ ] **Step 4: Add the speaker toggle to the kiosk top bar.** In `static/index.html`, between the mode switch and the STOP button:

```html
    <button type="button" id="btn-sound" aria-pressed="false" title="Play sound on this device">&#128263;</button>
```

- [ ] **Step 5: Wire it in `static/js/grid.js`** (in the "controls" section):

```js
const soundBtn = document.getElementById('btn-sound');
function renderSoundBtn(on) {
  soundBtn.textContent = on ? '\u{1F50A}' : '\u{1F507}'; // speaker / muted speaker
  soundBtn.classList.toggle('on', on);
  soundBtn.setAttribute('aria-pressed', String(on));
}
soundBtn.addEventListener('click', () => BB.setAudioPlayer(!BB.isAudioPlayer()));
BB.on('audiorole', (msg) => renderSoundBtn(msg.player));
renderSoundBtn(BB.isAudioPlayer());
```

- [ ] **Step 6: Style it in `static/css/batterbox.css`** (next to the `#btn-stop` rules):

```css
/* Device audio-role toggle: lit green = this device is the speaker
   (plays WS play events); dark = silent controller. */
#btn-sound {
  flex: 0 0 auto;
  min-width: 84px;
  font-size: 30px;
  padding: 10px 12px;
}
#btn-sound.on {
  background: #14532d;
  border-color: var(--ok);
}
```

- [ ] **Step 7: Update `docs/API.md`** (same commit). Replace the "Browser playback backend:" paragraph in the WebSocket section with:

> Browser playback backend — client audio roles: every WS client mirrors playback state, but only a client holding the **player** role (the Pi kiosk) plays `audio_url` via HTMLAudioElement at `volume` (0–100 → 0–1, `volume_boost_db` via WebAudio GainNode when nonzero) and reports natural end-of-song (`POST /api/playback/stop` echoing `play_id`). All other clients — phones, admin/editor tabs — are **controllers**: they send commands and render state but never produce sound and never report `ended`. The role is client-side: URL param `?player=1` (the kiosk launcher passes it) or the kiosk top-bar speaker toggle (persisted in localStorage, which overrides the param). On `stop`, the player halts immediately (<200ms). On connect, the server sends a `state` message. If no player-role client is connected under `AUDIO_BACKEND=browser`, plays are silent and the playing state clears only via STOP — use the kiosk speaker toggle or `AUDIO_BACKEND=server`.

- [ ] **Step 8: Verify — exactly one device plays.** Restart uvicorn so its access log is fresh, then open two headless pages and trigger a play:

```bash
chromium --headless=new --remote-debugging-port=9222 --no-sandbox \
  --autoplay-policy=no-user-gesture-required "http://localhost:8080/?player=1" &
chromium --headless=new --remote-debugging-port=9223 --no-sandbox \
  --autoplay-policy=no-user-gesture-required "http://localhost:8080/" &
sleep 3
curl -s -X POST localhost:8080/api/playback/play -H 'Content-Type: application/json' \
  -d '{"player_id": 1, "type": "walkup"}'
sleep 2
```

In the uvicorn log, expect **exactly one** `GET /media/clips/<id>.mp3` after the play (the controller never fetches audio; before this task there were two). Let the clip finish (seeded clips are short) and expect **exactly one** `POST /api/playback/stop`, then `GET /api/playback/state` returns `"status": "idle"`. Also confirm the toggle: on the plain (controller) page evaluate via CDP `document.getElementById('btn-sound').textContent` → muted glyph, and on the `?player=1` page → speaker glyph. Kill both Chromiums when done.

- [ ] **Step 9: Commit**

```bash
git add static/js/ws.js static/js/grid.js static/index.html static/css/batterbox.css docs/API.md
git commit -m "Client audio roles: only the designated player device plays sound"
git push
```

---

### Task 4: Kiosk launcher + docs catch-up

**Files:**
- Modify: `kiosk/start-kiosk.sh`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: the `?player=1` role param from Task 3.

- [ ] **Step 1: Point the Pi kiosk at the player role.** In `kiosk/start-kiosk.sh`, change the launch line:

```bash
echo "[batterbox-kiosk] launching ${CHROMIUM} in kiosk mode at ${URL} (audio player role)"
exec "${CHROMIUM}" \
    --kiosk "${URL}/?player=1" \
```

(everything else unchanged; `${URL}` has no trailing slash by default and a doubled slash is harmless if the user sets one).

- [ ] **Step 2: Update `AGENTS.md`:**
  - Conventions bullet (playback state): append — "Audio roles: only the client opened with `?player=1` (the Pi kiosk launcher does this) or with the kiosk speaker toggle ON plays WS `play` audio; every other page is a silent controller. The kiosk grid also live-refreshes on the WS `data_changed` event."
  - Cursor Cloud verify bullet: change "Verify via the UI at http://localhost:8080 (kiosk grid)" to "Verify via the UI at http://localhost:8080/?player=1 (kiosk grid; without `?player=1` the page is a silent controller — state updates but no audio element playback)".
  - Add a dated entry under "Lessons learned" summarizing the two defects fixed (remote-admin changes never reached open kiosks — WS carried playback only; and every connected browser played every song and raced `ended` stops).

- [ ] **Step 3: Update `README.md`:**
  - Line ~34 (PC quick start "Open http://localhost:8080"): change to "Open http://localhost:8080/?player=1 — the grid loads seeded... Audio plays through your PC's browser (the `?player=1` marks this tab as the speaker; other tabs/phones are silent controllers); GPIO is mocked."
  - "Audio: browser vs server backend" section: after the `AUDIO_BACKEND=browser` paragraph, add: "With the browser backend, only the **player-role** client makes sound — the kiosk launcher opens `/?player=1`, and the kiosk top bar has a speaker toggle to move the role to another device. Phones and admin tabs are silent controllers, so several open pages no longer echo the song over each other."
  - Troubleshooting list: add "**Tapping tiles is silent everywhere** — no device holds the audio player role. Tap the speaker toggle on the kiosk top bar (turns green), open the kiosk as `/?player=1`, or use `AUDIO_BACKEND=server`."

- [ ] **Step 4: Update `PROGRESS.md`.** Add under "Done (continued 2)":

```markdown
- [x] Kiosk live sync + client audio roles: WS `data_changed` event (scopes teams/players/hype) broadcast from all kiosk-relevant REST mutations; kiosk refreshes the grid on it (debounced, page-preserving) and after WS reconnect. Client audio roles: only `?player=1` (Pi kiosk launcher) or the top-bar speaker toggle plays WS audio; phones/admin tabs are silent controllers and no longer race `ended` stops. Verified with two headless Chromium clients: one media fetch + one stop report per play; live team rename/active-team switch reflected on an open kiosk in <2s.
```

- [ ] **Step 5: Line-ending check** (repo lesson: CRLF shebang kills the Pi): `head -c 60 kiosk/start-kiosk.sh | od -c` — no `\r` anywhere. `.gitattributes` forces LF but verify anyway.

- [ ] **Step 6: Commit and push**

```bash
git add kiosk/start-kiosk.sh AGENTS.md README.md PROGRESS.md
git commit -m "Kiosk launcher passes player role; document live sync + audio roles"
git push
```

- [ ] **Step 7: Final smoke pass.** Restart the server fresh, re-run the Task 1 WS listener check and the Task 3 one-fetch-per-play check once each, and confirm `GET /api/playback/state` and the kiosk UI agree after a full play→ended cycle. Update the PR body with verification results.

## Out of scope (deliberate)

- Admin page live refresh (`admin.js` still loads on demand — two simultaneous admins are not a field scenario; forms in progress must not be yanked out from under the editor).
- Server-side tracking of client roles (`/ws?role=...`): the server doesn't need to know; client-side gating is sufficient and keeps the WS contract additive.
- End-of-song watchdog for the "no player connected" browser-backend case: documented trade-off, mpv backend covers headless.
