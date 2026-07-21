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

- 2026-07-21: yt-dlp pins go stale fast — 2025.6.9 failed with "No video formats found" against current YouTube; bumped to 2026.7.4 and imports work. If imports break, check PyPI for a newer yt-dlp first.
- 2026-07-21: Git Bash mangles container paths in `docker exec` (e.g. `/data/x` → `C:/Program Files/Git/data/x`). Prefix with `MSYS_NO_PATHCONV=1`.
- 2026-07-21: `docker compose restart` has no `-q` flag (Docker Compose 2.29+); use plain `restart` and redirect output.
- 2026-07-21: First-run smoke test needs a real clip — playback endpoints correctly 404 until a player has an active clip of the requested type.
- 2026-07-21: Vendored wavesurfer core and regions plugin are NOT from the same release line: plugin `Region.play()` only forwards `end` when called with a truthy arg (`region.play(true)`), and `loop` is unsupported/ignored. Always preview via core `ws.play(region.start, region.end)` — it stops at `end` via `stopAtPosition`. If re-vendoring, grab both dist files from the same exact version.
- 2026-07-21: Docker Desktop on Windows: bind-mounting a Git-Bash `/tmp/...` path mounts the Linux VM's /tmp, not Windows', and old data persists across runs invisibly. For throwaway test containers use a named volume (`docker volume rm` between runs) — that's how a stale DB fake-passed a "fresh install" test.
- 2026-07-21: Seeded clips (seed/clips/*.mp3 via seed.json "clips" arrays) intentionally have NULL source_file — they're not re-editable in the trim editor (409 "no stored source"); re-import to re-trim. Bundling full sources would bloat the repo.
- 2026-07-21: `setPointerCapture` + mid-drag `insertBefore` = Chrome fires `lostpointercapture` and the drag dies silently (move/up listeners on the handle never fire again — reorder never POSTs). For pointer-based DnD, attach `pointermove`/`pointerup`/`pointercancel` to **window** at pointerdown and skip pointer capture entirely. Reproduced/verified with a CDP harness (headless Chrome + Input.dispatchMouseEvent) — great pattern for drag bugs.
- 2026-07-21: Sending `""` for an optional numeric field 422s the whole PATCH (pydantic int|None). Frontend sends `null` for blank jersey numbers.
