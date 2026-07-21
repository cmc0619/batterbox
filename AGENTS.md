# BatterBox — Agent Guide

Big league music for big league moments. Raspberry Pi–hosted walk-up song player. Full spec context lives in git history and `PROGRESS.md`.

## Commands

- Dev run: `docker compose up --build` → http://localhost:8080
- Pi run: `docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d`
- Backend-only local run (no Docker): `pip install -r requirements.txt && DATA_DIR=./data MOCK_GPIO=true uvicorn app.main:app --port 8080`
- No test suite yet — verify manually against Acceptance Criteria in PROGRESS.md.

## Architecture

- `app/` — FastAPI backend. `routers/` = REST per `docs/API.md`, `services/` = audio playback, clip pipeline (yt-dlp/ffmpeg), GPIO.
- `static/` — no-build JS SPA: `index.html` (kiosk 1024×600 + phone responsive), `admin.html` (roster/teams/clips, touch drag-drop reorder), `edit.html` (wavesurfer trim editor). wavesurfer is **vendored** in `static/vendor/` — never CDN at runtime (field has no internet).
- `data/` — SQLite DB + clips/photos/sources. Mounted volume; never commit contents.
- `docs/API.md` — binding backend↔frontend contract. Change it in the same commit as any API change.
- `kiosk/start-kiosk.sh` — Chromium kiosk launcher for the Pi (runs on host, not in Docker).

## Conventions

- Playback state lives ONLY on the server; clients receive it via WebSocket (`/ws`). Default playback backend is `browser` (HTMLAudioElement) because Docker on PC can't reach host speakers; `AUDIO_BACKEND=server` uses mpv inside the container (Pi option).
- GPIO handlers and mock keyboard shortcuts call the same playback REST endpoints — one code path.
- UI rules: exactly 1024×600 kiosk layout, min ~18px text, huge touch targets, no hover-dependent interaction. Tap = walk-up clip, long-press 600ms = home-run clip.
- Commit + push autonomously after each verified slice. Keep this file and PROGRESS.md current in the same commits.

## Lessons learned

_(append dated entries whenever something bites)_

- (placeholder)
