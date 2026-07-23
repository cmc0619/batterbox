# BatterBox — Progress

## Done
- [x] Repo scaffold, API contract (docs/API.md), agent guide, seed data
- [x] Backend (FastAPI, SQLite, routers, clip pipeline, playback, GPIO mock) — host-smoke-tested
- [x] Frontend (kiosk grid, admin touch reorder, clip editor, Walter Walkup, vendored wavesurfer 7.12.11)
- [x] Docker + kiosk script + README
- [x] Integration verified in Docker on PC (2026-07-21): build, seed, YouTube import, peaks/suggest, ffmpeg trim+loudnorm, upload import, play/stop/next state machine, restart persistence, all static assets 200

## In progress
- [ ] Human eyeball pass: open http://localhost:8080 at 1024×600 and on a phone; check tile layout, long-press feel, drag reorder
- [ ] Real GPIO test on the Pi 4 (docker-compose.pi.yml)

## Pi 4 first-boot checklist (real hardware)
- [ ] `docker compose logs app` shows `[gpio] pin factory: LGPIOFactory` (ERROR lines = buttons dead: lgpio missing or /dev/gpiochip0 not mapped)
- [ ] Physical buttons edge-detect: STOP / next batter / volume ±
- [ ] One Bluetooth speaker: pair via kiosk BT button (or admin) + full playback cycle (BlueZ over mounted D-Bus socket)
- [ ] Admin Wi-Fi hotspot start/stop via nmcli (container root authorized by NetworkManager polkit)
- [ ] Radios unblocked: `rfkill list` on first boot if Wi-Fi/BT seems dead
- [ ] Prefer 5GHz Wi-Fi when a Bluetooth speaker is paired (BT shares 2.4GHz airtime)
- [ ] Issue #5 — fix implemented (persistent bluetoothctl session over a pty hosts a NoInputNoOutput auto-accept agent for the whole pairing window; auto-answers yes/no prompts, trusts devices on pairing; verified against a stateful bluetoothctl stub); still needs Pi + speaker hardware confirmation
- [ ] Issue #6 — suspected: Wi-Fi real-radio divergences (rollback paths verified against an nmcli stub only); one-sitting Pi verification checklist in the issue

## Done (continued)
- [x] Clip re-edit: saved clips reopen in the editor (admin "Edit" button → edit.html?clip_id=N) with original source audio + saved trim region; PATCH /api/clips/{id} re-renders from the stored source. source_file column + non-destructive migration; pre-existing clips backfilled by timestamp/duration matching.
- [x] Pitcher walkout mode: third clip type `walkout` (clips table CHECK rebuilt in-place for existing DBs), admin WALKOUT intake group per player, kiosk PITCHERS top-bar toggle (grid = present players with active walkout clips, tap = walkout, long-press = homerun). Default snippet length 12s → 30s (migrates only untouched defaults).
- [x] Bluetooth speaker pairing from the kiosk: BT top-bar button (flashing blue while discoverable, solid blue dot when connected), `/api/bluetooth/*` endpoints driving BlueZ via bluetoothctl over the host D-Bus socket (docker-compose.pi.yml), 120s auto-expiring pairing mode, optional pairing LED on GPIO 26 (BCM). Gracefully unavailable on PC dev (verified: status 200 available=false, pairing/connect 400).
- [x] Admin-configurable Wi-Fi hotspot: `/api/wifi/*` endpoints driving host NetworkManager via nmcli over the same D-Bus socket (hotspot profile con-name `batterbox`, band bg / 2.4GHz), credentials in settings table (`wifi_ssid` default `BatterBox`, `wifi_password` default `bigleague1`, plain text by design), Admin → Wi-Fi Hotspot section (status line polled 10s, SSID/password prefill, Save/Start/Stop with disconnect confirm). Validation before save (bad values never overwrite good settings); settings-only save works with Wi-Fi unavailable. PC-dev degradation verified on port 8093 (status available=false, settings POST persists, hotspot POST 400, bad password 400 with settings untouched). Real-radio behavior untested — needs Pi hardware.
- [x] Hype clips + kiosk O/D/H mode switch: new `hype` table + `DATA_DIR/hype/<id>.mp3` + `/api/hype/*` endpoints reusing the player-clip import/render pipeline (youtube/upload jobs, peaks, one-pass ffmpeg, edit_context/rerender) keyed by title (1–80 chars) instead of player/type; `POST /api/playback/play_hype` (WS play with type "hype", player_id null). Kiosk top bar: removed VOL−/VOL+/vol-label (volume stays on mock-GPIO bar / physical GPIO / settings) and the PITCHERS toggle — replaced by O/D/H buttons (O = batting grid, D = defense/walkout grid = old PITCHERS behavior, H = hype grid, tap-only). Hype tiles highlight on hype play events; Walter dances for any playing status. Editor: `edit.html?hype=1` (title input + hype import/save) and `?hype_clip_id=N` (re-edit). Admin: Hype Clips section (list, ▶ Test, Edit, Delete, ＋ Add). Verified live on port 8096 against a copy of the dev data.

## Acceptance criteria checklist
- [x] 1. `docker compose up` on PC → grid loads, tiles seeded from seed.json (2 teams, 16+8 players → paging active)
- [x] 2. Tile tap plays; instant switch; STOP ≤200ms (browser playback via WS; state machine curl-verified — human ear check pending)
- [x] 3. Full clip workflow in Docker on PC: YouTube URL → waveform → drag → preview → save → plays from grid (verified end-to-end with yt-dlp 2026.7.4; rendered 12.0s 192kbps loudnorm'd MP3)
- [x] 4. Keyboard mock buttons drive same code path as GPIO (mock shortcuts + GPIO handlers both call playback REST)
- [x] 5. README documents Pi deploy incl. kiosk autostart + hotspot notes
- [x] 6. Walter Walkup on screen. Headphones, cap, mustache. Present and animating.

## Done (continued 2)
- [x] Hardening pass (2026-07-22): `/media` now mounts only the four media subdirs (clips/photos/hype/sources) so the SQLite DB and mpv socket at the volume root are no longer downloadable; server-backend (mpv) playback clears "playing" state on natural end-of-file via a process watcher thread (browser backend already did this through the client `ended` handler); import jobs evicted from memory after 1h (dict entry only — source files stay for re-edit); roster reorder validates the id list is the complete team exactly once (400 otherwise, preventing silent sort_order corruption from partial lists).
- [x] Hardening pass 2 (2026-07-22, from independent model review): playback transitions fully serialized via op lock (no orphaned mpv processes under concurrent plays; mpv start failure returns idle+warning instead of stuck "playing"; EOF watcher armed after the play broadcast); per-play `play_id` token so a slow client's `ended` can't stop the next clip (WS play/state + optional stop body); settings PATCH null no longer poisons the DB ("None" string), NaN/Infinity trims/boost rejected at the model, snippet length bounded 3–300, boost ±24dB; Wi-Fi hotspot/client transitions persist credentials only on success and restore the previous hotspot on failure (verified with a stateful nmcli stub); import pipeline bounded (30-min source duration cap before PCM decode, yt-dlp noplaylist+50MB+timeout, 8-job backlog → 429); `_jobs` map locked, evicted on read too, abandoned sources deleted when unreferenced; cascade deletes remove now-unreferenced trim sources; renders use unique temp names + per-item lock (concurrent PATCHes can't corrupt each other); creates render before inserting the row (no playable-but-404 window) and "first clip active" is decided inside the insert transaction (exactly one active under concurrent saves); first team auto-activates and deleting the active team hands off to a survivor; photo upload bounded-read + magic-byte check + temp-then-replace; Bluetooth pairing start 400s honestly when the adapter can't enter pairing mode; README GPIO wiring table corrected to match code defaults (Next=23, Vol+=27, Vol−=22). Full end-to-end regression on a fresh DB after all changes.
- [x] Review lows (2026-07-22): `PORT` honored by the entrypoint (`${PORT:-8080}` — Pi already answers on :80 via the compose `80:8080` mapping, PC dev stays 8080); blank jersey number stored as null from BOTH forms and rendered as nothing (no `#0`/`#?`) on kiosk tiles and admin rows; starting a roster drag collapses any open edit panel (it used to stay stranded under the wrong player after reorder); editor import debounced for touchscreens (buttons disabled while a job is in flight, URL cleared once accepted, job polling retries up to 5 transient failures instead of dying — and re-enables the buttons on job error). L2–L4 verified with a headless-Chrome CDP harness (including a real drag via Input.dispatchMouseEvent and the real yt-dlp error path).

## Pending scope notes
- Multiple teams, >15 players (paged 5×3 grid), multiple clips per player (walkup tap / homerun long-press 600ms), touch drag-drop reorder — all implemented.
- Dev data note: ./data currently holds two demo clips for Bobby 'Rocket' Reyes (walkup 12s, homerun 8s, from "Me at the zoo") — delete via admin UI if unwanted.
