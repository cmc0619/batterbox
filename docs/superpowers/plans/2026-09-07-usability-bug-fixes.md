# Usability Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the ten approved user-visible reliability bugs without security hardening, new dependencies, broad abstractions, or a committed test framework.

**Architecture:** Keep the current FastAPI, SQLite, no-build JavaScript, and shell-script structure. Make focused state/lifecycle corrections inside the existing modules, with one logical commit per independently verifiable subsystem.

**Tech Stack:** Python 3.12, FastAPI, SQLite, browser ES modules, WebSocket, HTMLAudioElement, mpv, nmcli, Bash.

## Global Constraints

- Preserve opt-in, multi-listener browser audio roles.
- Manual STOP must remain immediate and must stop every backend.
- Do not add authentication, hostile-client protections, yt-dlp limits, runtime dependencies, or a committed test suite.
- Keep `docs/API.md` in the same commit as WebSocket/API semantic changes.
- Keep implementation minimal; add only state comparisons needed by reproduced races.
- Verify every slice against a running no-Docker server before its final commit.
- Update `PROGRESS.md` before final handoff.

---

### Task 1: Browser Playback Transitions

**Files:**
- Modify: `static/js/ws.js:87-246`

**Interfaces:**
- Consumes: existing `joinCurrentPlay()`, `startAudio()`, `handlePlay()`, `handleStop()`, and `setAudioPlayer()`.
- Produces: module-local `playbackGeneration: number`; `startAudio()` callbacks that apply only to their originating transition.

- [ ] **Step 1: Reproduce the deferred-start bug**

Run a one-off Node browser shim that loads `ws.js`, starts an offset play, calls STOP before dispatching `loadedmetadata`, and then dispatches metadata. Record that `audio.play()` is called after STOP. Repeat with a newer source and record that the old offset is applied to it.

- [ ] **Step 2: Implement transition invalidation**

Add a module-local counter:

```js
let playbackGeneration = 0;
```

Increment it when disabling the player role, handling STOP, and accepting a new audio source. In `startAudio()`, capture the incremented value and have both the deferred metadata callback and `start()` return unless:

```js
generation === playbackGeneration
  && isPlayer
  && activePlayId === playId
  && audio.src === new URL(audioUrl, location.href).href
```

Do not add a reusable coordinator or retry layer.

- [ ] **Step 3: Correct join-current-play freshness**

Capture `playbackGeneration` before `GET /api/playback/state`. When the request resolves, discard it only if that generation changed while the request was pending. Remove the comparison that rejects any server `play_id` different from stale `lastPlayId`; a newer server play missed during WebSocket downtime is legitimate.

- [ ] **Step 4: Verify the browser transitions**

Re-run the one-off shim and verify:

- metadata after STOP does not call `play()`;
- metadata after role-off does not call `play()`;
- metadata from an older source cannot seek a newer source;
- a REST state with play ID 13 is accepted when local `lastPlayId` is 12 and no local transition occurred during the request;
- a REST response is rejected when a play event occurs while it is pending.

- [ ] **Step 5: Commit**

```bash
git add static/js/ws.js
git commit -m "Keep deferred browser audio tied to its play"
```

---

### Task 2: Team and Roster UI Consistency

**Files:**
- Modify: `static/js/grid.js:220-267`
- Modify: `static/js/admin.js:10-179,350-370,585-604`

**Interfaces:**
- Consumes: existing REST endpoints and `rosterSeq`.
- Produces: atomic kiosk team/roster rendering; Admin `playerLoadSeq`; pending-state Add buttons.

- [ ] **Step 1: Reproduce stale team displays**

Use CDP request interception to delay team A's roster, select team B, release B first, then release A. Confirm Admin ends with A players under B's heading. For kiosk, make the newly active team's roster request fail and confirm old-team tiles remain under the new team name.

- [ ] **Step 2: Commit kiosk team and roster together**

In `loadTeams()`, fetch the selected roster before assigning `currentTeamId`, `teamNameEl`, and `players`. Apply all four values only after both requests succeed and `seq === rosterSeq`. If the team changed and its roster request fails, clear `players`, reset `page`, render empty tiles, and leave a visible refresh error rather than retaining tappable old-team players.

- [ ] **Step 3: Keep Admin roster responses with their team**

Add `playerLoadSeq`. `loadPlayers()` captures both `selectedTeamId` and a new sequence value before fetching. It assigns `players` and renders only when both still match. A stale response returns without touching the current list.

- [ ] **Step 4: Support jersey-only players**

On edit, submit:

```js
body: { name: ni.value.trim(), jersey_number: jersey }
```

On create, accept an empty trimmed name when `jersey !== null`; show `Enter a name or jersey number.` only when both are blank.

- [ ] **Step 5: Prevent duplicate Add requests**

For Add Team and Add Player, capture the button, return immediately when disabled, set `disabled = true` before the first `await`, and restore it in `finally`. Keep the existing field clearing and reload behavior.

- [ ] **Step 6: Verify UI behavior**

Repeat the CDP race and roster-failure scenarios. Then double-click Add Team/Add Player and inspect the network log and database: exactly one POST and one row per action. Create and edit a jersey-only player and verify its kiosk tile uses the jersey placeholder.

- [ ] **Step 7: Commit**

```bash
git add static/js/grid.js static/js/admin.js
git commit -m "Keep roster UI aligned with the selected team"
```

---

### Task 3: Stable Snippet-Length Setting

**Files:**
- Modify: `app/db.py:225-232`

**Interfaces:**
- Consumes: fresh-database default `default_snippet_length = "30"`.
- Produces: persisted values in the documented 3–300 range that survive every `init_db()`.

- [ ] **Step 1: Reproduce the restart reset**

In a temporary `DATA_DIR`, call `init_db()`, set `default_snippet_length` to `12`, call `init_db()` again, and verify the current code returns `30`.

- [ ] **Step 2: Remove the recurring historical update**

Delete the unconditional `UPDATE settings SET value = '30' WHERE ... value = '12'` block from `_migrate()`. Do not add a migration table or sentinel: fresh databases already seed 30, and current installations have already run the old migration.

- [ ] **Step 3: Verify persistence**

Repeat the temporary-database script and verify 12 remains 12 after repeated `init_db()` calls, while a fresh database starts at 30.

- [ ] **Step 4: Run the server**

Start the no-Docker server with a temporary `DATA_DIR`, PATCH the setting to 12, restart the process, and verify `GET /api/settings` still returns 12.

- [ ] **Step 5: Commit**

```bash
git add app/db.py
git commit -m "Preserve an intentional 12-second snippet setting"
```

---

### Task 4: Server-Owned mpv End-of-Song

**Files:**
- Modify: `app/services/audio.py:205-368`
- Modify: `docs/API.md` WebSocket playback section

**Interfaces:**
- Consumes: `_op_lock`, `_eos_timer`, `EOS_GRACE_SEC`, `play_id`, and `server_eos`.
- Produces: `_watch_mpv(proc, play_id)` that schedules a guarded one-second stop; automatic stops ignored for server-owned plays.

- [ ] **Step 1: Reproduce issue #28**

With an mpv stub that remains alive, start a server-backend play and send `POST /api/playback/stop` with its current `play_id`. Verify the stub is terminated. With a stub that exits naturally, record that the stop broadcast has no grace.

- [ ] **Step 2: Make server ownership explicit**

Set `server_eos` true whenever mpv owns the play, regardless of stored duration. In `stop(play_id=...)`, return current state without halting when the matching play has `server_eos is True`; a bodyless manual STOP still calls `_halt()`.

- [ ] **Step 3: Give browser listeners completion grace**

Pass `play_id` into `_watch_mpv`. After mpv exits, acquire `_op_lock`, confirm the process still owns the current play, clear only `_mpv_proc`/`_mpv_ipc`, and arm `_eos_timer` for `EOS_GRACE_SEC`. Keep state playing during that second. Reuse `_eos_fire(play_id)` so manual STOP or a newer play cancels/supersedes the delayed stop.

Refactor `_arm_eos_timer` to accept an exact delay. Browser playback passes `duration + EOS_GRACE_SEC`; mpv EOF passes `EOS_GRACE_SEC`.

- [ ] **Step 4: Update the contract**

Document that `server_eos: true` covers both the browser timer and mpv EOF watcher, that play-ID-bearing automatic stops are ignored for such plays, and that mpv gives browser listeners one second to finish.

- [ ] **Step 5: Verify server playback**

Using the live server and mpv stub, verify:

- automatic current-play stop does not terminate mpv;
- manual STOP terminates it immediately;
- natural EOF leaves state playing for about one second, then emits stop;
- a newer play during grace cancels the old delayed stop;
- browser-backend duration timers still end at duration plus one second.

- [ ] **Step 6: Commit**

```bash
git add app/services/audio.py docs/API.md
git commit -m "Make mpv authoritative for end of song"
```

---

### Task 5: Correct mpv ALSA Device Names

**Files:**
- Modify: `app/services/audio.py:184-188`
- Modify: `README.md:150-190`
- Modify: `docker-compose.pi.yml:40-47`

**Interfaces:**
- Consumes: persisted `audio_output`.
- Produces: mpv `--audio-device=alsa/hw:...` or `alsa/plughw:...` for bare ALSA values.

- [ ] **Step 1: Capture the bad command**

Stub `subprocess.Popen`, set `audio_output=plughw:1,0`, call `_server_play`, and record the current `--audio-device=plughw:1,0` argument.

- [ ] **Step 2: Normalize only bare ALSA hardware names**

Before appending the option:

```python
if audio_output.startswith(("hw:", "plughw:")):
    audio_output = f"alsa/{audio_output}"
```

Leave `auto`, `alsa`, and already backend-prefixed identifiers unchanged.

- [ ] **Step 3: Correct operator guidance**

Use `alsa/plughw:1,0` in examples and tell operators to copy the exact identifier from `mpv --audio-device=help`.

- [ ] **Step 4: Verify command construction**

Check stubbed commands for `auto`, `plughw:1,0`, `hw:0,0`, `alsa/plughw:1,0`, and `pulse/auto`.

- [ ] **Step 5: Commit**

```bash
git add app/services/audio.py README.md docker-compose.pi.yml
git commit -m "Pass valid ALSA device names to mpv"
```

---

### Task 6: Serialized, Honest Wi-Fi Transitions

**Files:**
- Modify: `app/services/wifi.py:18-339`

**Interfaces:**
- Consumes: `_run()` and current nmcli command sequences.
- Produces: `_radio_lock: threading.RLock`; `_active_connections() -> tuple[dict[str, str] | None, str]`.

- [ ] **Step 1: Reproduce unknown-state behavior**

Use the existing style of stateful nmcli stub, but fail `connection show --active`. Verify current hotspot start/client connect proceeds as if no hotspot exists and hotspot-off can report success.

- [ ] **Step 2: Preserve discovery failure**

Return `(None, detail)` when active-state discovery fails and `(connections, "")` on success. `get_status()` reports `mode="unknown"` and the detail when the result is `None`.

Before any destructive radio command, `enable_hotspot()` and `connect_client()` return an error when discovery is unknown. `disable_hotspot()` also returns an error unless the post-command status can verify the result.

- [ ] **Step 3: Serialize mutations**

Add a module-level `threading.RLock` and hold it for the complete body of `enable_hotspot()`, `connect_client()`, and `disable_hotspot()`. Use `RLock` because those functions call `get_status()` while finishing. Do not add queues or background workers.

- [ ] **Step 4: Verify nmcli sequences**

With the stub, verify:

- active-state failure executes no delete/down/connect command;
- two concurrent mutations execute as two complete, non-interleaved command sequences;
- failed client connection restores an active hotspot;
- failed hotspot replacement restores prior credentials;
- successful status parsing and off-Pi `available=false` behavior remain unchanged.

- [ ] **Step 5: Run the live server**

Call every `/api/wifi/*` endpoint off-Pi and verify the documented `available=false` degradation remains clean with no traceback.

- [ ] **Step 6: Commit**

```bash
git add app/services/wifi.py
git commit -m "Serialize Wi-Fi changes and preserve unknown state"
```

---

### Task 7: Reliable Pi Kiosk Startup

**Files:**
- Modify: `kiosk/start-kiosk.sh:27-73`
- Modify: `README.md` kiosk startup and troubleshooting sections

**Interfaces:**
- Consumes: Pi compose's host port 80 and optional `BATTERBOX_URL`.
- Produces: default `URL=http://localhost`; one threshold warning followed by continued health checks.

- [ ] **Step 1: Reproduce current URL and timeout behavior**

Put a curl stub first on `PATH`. Verify the launcher probes localhost:8080 by default and reaches Chromium after the wait threshold even when every probe fails.

- [ ] **Step 2: Use the Pi mapping**

Change the default to:

```bash
URL="${BATTERBOX_URL:-http://localhost}"
```

Keep the explicit override unchanged.

- [ ] **Step 3: Continue waiting after the warning**

Replace the timeout `break` with a warning emitted once. Continue the same two-second health probe until it succeeds. Print “app is up” only after a successful probe.

- [ ] **Step 4: Update deployment guidance**

Document the port-80 default, `BATTERBOX_URL` override, and the fact that a slow backend keeps the launcher waiting instead of opening an unrecoverable Chromium error page.

- [ ] **Step 5: Verify the launcher**

Run `bash -n`. With curl/Chromium stubs, verify default port 80, custom URL, no Chromium launch while unhealthy, and one launch immediately after the first healthy probe.

- [ ] **Step 6: Commit**

```bash
git add kiosk/start-kiosk.sh README.md
git commit -m "Keep the Pi kiosk waiting for its server"
```

---

### Task 8: Full Regression and Project Record

**Files:**
- Modify: `PROGRESS.md`
- Modify only if verification finds contract/documentation drift: `AGENTS.md`, `docs/API.md`, `README.md`

**Interfaces:**
- Consumes: all preceding commits.
- Produces: verified PR revision and recorded evidence.

- [ ] **Step 1: Run static checks**

Parse every Python file with `ast.parse`, every frontend module with `node --input-type=module --check`, and run `bash -n` on shell scripts plus `git diff --check`.

- [ ] **Step 2: Run live-server regression**

Start:

```bash
DATA_DIR=./data MOCK_GPIO=true .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Verify static pages, settings persistence, seeded roster playback, stop, next, volume, WebSocket state/data refresh, jersey-only player CRUD, and off-Pi Bluetooth/Wi-Fi degradation.

- [ ] **Step 3: Run focused browser scenarios**

With headless Chromium/CDP, verify deferred audio cancellation, join after disconnect, active-team roster failure, stale Admin team response, and duplicate-submit suppression.

- [ ] **Step 4: Run mpv/nmcli/kiosk stubs**

Re-run the exact focused scenarios from Tasks 4–7 and save concise evidence for the PR body.

- [ ] **Step 5: Update project history**

Add one dated `PROGRESS.md` entry naming all ten fixed behaviors and the verification evidence. Add an `AGENTS.md` lesson only if verification exposed a reusable, non-obvious failure mode.

- [ ] **Step 6: Commit**

```bash
git add PROGRESS.md AGENTS.md docs/API.md README.md
git commit -m "Record usability regression verification"
```

- [ ] **Step 7: Push and update the PR**

```bash
git push -u origin cursor/usability-bug-fixes-d561
```

Update the ready-for-review PR body with the final commit summary and exact live/stub/CDP verification results.
