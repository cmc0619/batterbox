# BatterBox — Agent Guide

Big league music for big league moments. Raspberry Pi–hosted walk-up song player. Full spec context lives in git history and `PROGRESS.md`.

> ## Change policy (owner directive, updated 2026-07-25 — supersedes the 2026-07-23 code freeze)
> The freeze is lifted; the project is under active development. Application code (`app/**`, `static/**`) may be changed as part of an agreed task. Still required every time: keep `docs/API.md` in the **same commit** as any API/WS change; verify against a running server before committing (there is no test suite — see Commands); one logical change per commit. Propose the approach and get the owner's OK **before** starting anything large or hard to reverse — schema migrations, contract changes, new runtime dependencies, or UX rework.

## Commands

- Dev run: `docker compose up --build` → http://localhost:8080
- Pi run: `docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d`
- Backend-only local run (no Docker): `pip install -r requirements.txt && DATA_DIR=./data MOCK_GPIO=true uvicorn app.main:app --port 8080`
- No test suite yet — verify manually against Acceptance Criteria in PROGRESS.md.

## Architecture

- `app/` — FastAPI backend. `routers/` = REST per `docs/API.md`, `services/` = audio playback, clip pipeline (yt-dlp/ffmpeg; shared by player clips and hype clips), GPIO, Bluetooth pairing (`bluetooth.py` — drives host BlueZ via `bluetoothctl` over the D-Bus socket mounted by docker-compose.pi.yml; degrades to available=false off-Pi), Wi-Fi hotspot (`wifi.py` — drives host NetworkManager via `nmcli` over the same D-Bus socket; hotspot profile con-name `batterbox`; degrades to available=false off-Pi). Hype clips (crowd stingers, not tied to a player) have their own `hype` table + `DATA_DIR/hype/<id>.mp3` files but reuse the player-clip import/render pipeline.
- `static/` — no-build JS SPA: `index.html` (kiosk 1024×600 + phone responsive), `admin.html` (roster/teams/clips, touch drag-drop reorder), `edit.html` (wavesurfer trim editor). wavesurfer is **vendored** in `static/vendor/` — never CDN at runtime (field has no internet).
- `data/` — SQLite DB + clips/photos/sources. Mounted volume; never commit contents.
- `docs/API.md` — binding backend↔frontend contract. Change it in the same commit as any API change.
- `kiosk/start-kiosk.sh` — Chromium kiosk launcher for the Pi (runs on host, not in Docker).

## Conventions

- Playback state lives ONLY on the server; clients receive it via WebSocket (`/ws`). Default playback backend is `browser` (HTMLAudioElement) because Docker on PC can't reach host speakers; `AUDIO_BACKEND=server` uses mpv inside the container (Pi option). Audio roles: only the client opened with `?player=1` (the Pi kiosk launcher does this) or with the kiosk speaker toggle ON plays WS `play` audio; every other page is a silent controller. An explicit `?player=0|1` beats the stored toggle at load. Roles are **opt-in, multi-listener by design** — several devices may play at once (kiosk + a spectator's phone on a Bluetooth earpiece), no client can hijack or revoke another's role, and "one speaker" is an operator convention, not an enforced invariant. **End of song belongs to the server** (`server_eos` on the play event): clients don't report `ended` when the server knows the clip's duration, so no listener can cut a clip short and none can strand it. A device that opts in mid-song joins the clip at the server's `elapsed_sec`. The kiosk grid also live-refreshes on the WS `data_changed` event.
- GPIO handlers and mock keyboard shortcuts call the same playback REST endpoints — one code path.
- UI rules: exactly 1024×600 kiosk layout, min ~18px text, huge touch targets, no hover-dependent interaction. Kiosk top bar has an O/D/H mode switch: O = offense (tap = walk-up clip, long-press 600ms = home-run clip), D = defense (players with an active walkout clip; tap = walkout, long-press = homerun), H = hype (crowd-stinger tiles, tap only). Volume is NOT on the top bar — it lives on the mock-GPIO bar (dev), physical GPIO buttons (Pi), and admin settings.
- Commit + push autonomously after each verified slice. Keep this file and PROGRESS.md current in the same commits.
- PRs: always create as **ready for review**, never draft — the repo's auto-reviewers (CodeRabbit, Greptile) skip draft PRs.

## Cursor Cloud specific instructions

- Skip Docker in the cloud VM — the fastest, most reliable run is the no-Docker backend (see Commands). Deps live in a `.venv` at the repo root (gitignored); the startup update script creates/refreshes it. Run with `DATA_DIR=./data MOCK_GPIO=true .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080`.
- First start auto-seeds `./data` from `seed.json` + `seed/clips/*.mp3` (2 teams, 24 players, active clips for the first 3 Sandlot players). No migration/seed command to run. The `./data` dir is gitignored — never commit it.
- Verify via the UI at http://localhost:8080/?player=1 (kiosk grid; without `?player=1` the page is a silent controller — state updates but no audio element playback) — tap a seeded player tile (e.g. Bobby 'Rocket' Reyes #3) to play a walk-up clip. Playback state is server-side (WS `/ws`); browser backend needs a client's HTMLAudioElement `ended`/stop to clear "playing" (see lesson below).
- Bluetooth (`/api/bluetooth/*`) and Wi-Fi hotspot (`/api/wifi/*`) intentionally report `available=false` off-Pi — that is expected, not a failure.
- `.venv/bin/uvicorn --reload` hot-reloads on code edits; the DB/seed persists in `./data` across restarts.

## Accepted by design — don't re-litigate these

Automated reviewers keep filing these as defects. They are deliberate choices for
a private-LAN appliance (one Pi 4, one field, no internet). If a review raises
one, answer with this section instead of "fixing" it.

- **No authentication or authorization anywhere**, and permissive CORS
  (`allow_origins=["*"]`). Anyone who can reach the app is standing at the field.
- **Wi-Fi hotspot password stored and returned in plain text** — the admin page
  prefills it so the coach can read it aloud.
- **Multiple simultaneous audio "player" clients.** Roles are opt-in and
  client-side; the kiosk plus a spectator on a Bluetooth earpiece may both play
  the same clip, and no client can claim or revoke another's role. "One speaker"
  is an operator convention, not an invariant.
- **Permissive player/team names** — empty, whitespace-only and explicit-`null`
  accepted (null stored as `""`); mid-game roster entry is fog-of-war and a
  player may be just a jersey number. `jersey_number` must be ≥ 0. Only a 500 on
  any of these is a bug.
- **One shared SQLite connection behind a lock, no ORM, no migration framework.**
  Single-process and low-concurrency by design; upgrades are hand-written
  non-destructive steps in `db._migrate`.
- **Raspberry Pi 4 is the only target platform.**
- **No test suite** — verify against a running server and put the evidence in the
  PR body. Don't add pytest without asking.

## Lessons learned

_(append dated entries whenever something bites)_

- 2026-07-21: yt-dlp pins go stale fast — 2025.6.9 failed with "No video formats found" against current YouTube; bumped to 2026.7.4 and imports work. If imports break, check PyPI for a newer yt-dlp first.
- 2026-07-21: Git Bash mangles container paths in `docker exec` (e.g. `/data/x` → `C:/Program Files/Git/data/x`). Prefix with `MSYS_NO_PATHCONV=1`.
- 2026-07-21: `docker compose restart` has no `-q` flag (Docker Compose 2.29+); use plain `restart` and redirect output.
- 2026-07-21: First-run smoke test needs a real clip — playback endpoints correctly 404 until a player has an active clip of the requested type.
- 2026-07-21: Vendored wavesurfer core and regions plugin are NOT from the same release line: plugin `Region.play()` only forwards `end` when called with a truthy arg (`region.play(true)`), and `loop` is unsupported/ignored. Always preview via core `ws.play(region.start, region.end)` — it stops at `end` via `stopAtPosition`. If re-vendoring, grab both dist files from the same exact version.
- 2026-07-21: Docker Desktop on Windows: bind-mounting a Git-Bash `/tmp/...` path mounts the Linux VM's /tmp, not Windows', and old data persists across runs invisibly. For throwaway test containers use a named volume (`docker volume rm` between runs) — that's how a stale DB fake-passed a "fresh install" test.
- 2026-07-21: Seeded clips (seed/clips/*.mp3 via seed.json "clips" arrays) intentionally have NULL source_file — they're not re-editable in the trim editor (409 "no stored source"); re-import to re-trim. Bundling full sources would bloat the repo.
- 2026-07-21: `setPointerCapture` + mid-drag `insertBefore` = Chrome fires `lostpointercapture` and the drag dies silently (move/up listeners on the handle never fire again — reorder never POSTs). For pointer-based DnD, attach `pointermove`/`pointerup`/`pointercancel` to **window** at pointerdown and skip pointer capture entirely. Reproduced/verified with a CDP harness (headless Chrome + Input.dispatchMouseEvent) — great pattern for drag bugs.
- 2026-07-21: Sending `""` for an optional numeric field 422s the whole PATCH (pydantic int|None). Frontend sends `null` for blank jersey numbers.
- 2026-07-21: Browser playback backend had no server-side end-of-song detection — the server only learned a clip finished when a client's HTMLAudioElement `ended` fired and posted `/api/playback/stop` (ws.js). Without that, "playing" state (Walter, tile pulse) stuck forever. **Superseded 2026-07-25:** the server now arms its own end-of-clip timer from `duration_sec` (see `_arm_eos_timer`) and clients stay quiet when `server_eos` is true.
- 2026-07-25: Delegating end-of-song to "the client that's playing" stops working the moment more than one client can play: the first device to finish — or to background itself, or to hit a slow link — posted the stop and cut the song for everyone, and with zero player-role clients nobody reported at all. `play_id` doesn't help; it only filters stale stops from a PREVIOUS play, not a same-play stop from another device. If the server knows how long the media is, the server should own the end of it (mpv already did via `_watch_mpv`).
- 2026-07-25: `kill %1` does NOT kill headless Chrome in these test scripts — the wrapper re-execs, the job dies, the browser lives. A stale `?player=1` page from an earlier test then ran the OLD ws.js against the NEW server and reported `ended`, ending a "no listener connected" timer test 0.9s early and nearly passing off a wrong result as right. Kill browsers with `pkill -f "user-data-dir=/tmp/<dir>"` and confirm with `pgrep -af google-chrome` before timing anything.
- 2026-07-25: `new Audio()` elements are NOT in the DOM, so `document.querySelector('audio')` finds nothing and module-scoped `BB` isn't on `window` — a CDP harness can't probe playback directly. Wrap `window.Audio` via `Page.addScriptToEvaluateOnNewDocument` before navigating and collect instances on `window.__audios`; that inspects `currentTime`/`paused`/`src` without adding test hooks to production code.
- 2026-07-21: After a deploy, an open/cached kiosk page can run OLD js against NEW html (old grid.js → `getElementById('team-select')` → null deref → blank grid). All GET responses now send `Cache-Control: no-cache` (middleware in main.py) — revalidation with ETag/304 keeps it cheap on LAN. Symptom fix for users: one hard refresh.
- 2026-07-22: A Windows checkout can hand you CRLF shell scripts; a CRLF shebang makes Linux containers crash-loop with the utterly misleading `exec ./docker-entrypoint.sh: no such file or directory`. `.gitattributes` now forces `*.sh text eol=lf` — do not remove it. Diagnose with `head -c 60 file.sh | od -c` (look for `\r`).
- 2026-07-24: A clip's destination slot is recorded server-side at import and COMPARED against the `player_id`/`type` the client re-sends at save (`POST /api/clips` still takes both — the comparison is the point; don't drop it). The import endpoints took `player_id`/`type` and dropped them, so `POST /api/clips` filed the clip wherever the save said, and the editor silently defaulted an unknown `?type` to `walkup`: result, a home-run song sitting in a player's walk-up section with no error anywhere. Jobs now carry their owner and mismatched saves 400. General rule for this codebase: when a value is collected in step 1 and re-sent in step 3, the server must compare them — and a UI that can't tell which slot it's filling should refuse, never guess.
- 2026-07-25: Two multi-client defects fixed together: (1) the WS carried playback events only, so remote admin edits (active team, roster, clips) never reached an open kiosk — GPIO NEXT used the new server-side team while the touchscreen showed the old roster; now every kiosk-relevant REST mutation broadcasts `data_changed` (scopes teams/players/hype) and the kiosk refetches (debounced, page-preserving, also on WS reconnect). (2) ws.js played every WS `play` on every connected client (kiosk + phones + admin tabs = echo, and each raced an `ended` stop report); now only the player-role client (`?player=1` — kiosk launcher — or the top-bar speaker toggle, localStorage) plays audio and reports `ended`. Trade-off: browser backend with zero player-role clients = silent plays that only clear via STOP; the toggle makes that visible, mpv backend avoids it entirely.
- 2026-07-25: Seeding env-derived settings with `INSERT OR IGNORE` freezes the FIRST boot's value forever — `AUDIO_OUTPUT=plughw:1,0` in compose did nothing once the DB existed. And "apply env only when the var is present" doesn't work either: compose always sets the var (with a default). The pattern that works: store the last-seen env value in a sentinel row and re-apply the setting only when the env value *changed* since the previous boot — admin-PATCHed values survive restarts, compose edits still land. Corollary: a setting whose behavior is fixed at boot from env (`mock_gpio`) should be *reported* from config live, never mirrored into the DB, and never patchable.
- 2026-07-25: pip-audit the pins now and then — fastapi 0.115.6 resolved starlette 0.41.3, which carried two advisories that map 1:1 onto this app (Range-header DoS in StaticFiles = our entire UI/media serving; multipart event-loop blocking = our 50MB imports). Starlette is now pinned explicitly NEXT TO fastapi in requirements.txt (keep >= 0.49.1); when bumping fastapi, re-check the resolved starlette against GHSA before shipping.
- 2026-07-22: gpiozero is a FRONTEND ONLY — without a pin backend it silently falls back to mock GPIO on real hardware (buttons dead, zero errors). On Pi 4 the backend is `lgpio` (pip-builds with swig + build-essential, both purged in the Dockerfile layer) and it talks to `/dev/gpiochip0` (NOT `/dev/gpiomem`) — the Pi compose maps both. Entrypoint logs the pin factory when MOCK_GPIO=false; expect `LGPIOFactory`. Target platform is Pi 4 only.
