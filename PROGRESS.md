# BatterBox — Progress

## Done
- [x] Repo scaffold, API contract (docs/API.md), agent guide, seed data
- [x] Backend (FastAPI, SQLite, routers, clip pipeline, playback, GPIO mock) — host-smoke-tested
- [x] Frontend (kiosk grid, admin touch reorder, clip editor, Walter Walkup, vendored wavesurfer 7.12.11)
- [x] Docker + kiosk script + README
- [x] Integration verified in Docker on PC (2026-07-21): build, seed, YouTube import, peaks/suggest, ffmpeg trim+loudnorm, upload import, play/stop/next state machine, restart persistence, all static assets 200

## In progress
- [ ] Human eyeball pass: open http://localhost:8080 at 1024×600 and on a phone; check tile layout, long-press feel, drag reorder
- [ ] Real GPIO test on the Pi (docker-compose.pi.yml)

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

## Pending scope notes
- Multiple teams, >15 players (paged 5×3 grid), multiple clips per player (walkup tap / homerun long-press 600ms), touch drag-drop reorder — all implemented.
- Dev data note: ./data currently holds two demo clips for Bobby 'Rocket' Reyes (walkup 12s, homerun 8s, from "Me at the zoo") — delete via admin UI if unwanted.
