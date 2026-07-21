# BatterBox — Progress

## Done
- [x] Repo scaffold, API contract (docs/API.md), agent guide, seed data

## In progress
- [ ] Backend (FastAPI, SQLite, routers, clip pipeline, playback, GPIO mock)
- [ ] Frontend (kiosk grid, admin, clip editor, Walter Walkup)
- [ ] Docker + kiosk script + README

## Acceptance criteria checklist
- [ ] 1. `docker compose up` on PC → grid loads at 1024×600, tiles seeded from seed.json
- [ ] 2. Tile tap plays audio on PC speakers; instant switch; STOP ≤200ms
- [ ] 3. Full clip workflow in Docker on PC: YouTube URL → waveform → drag → preview → save → plays from grid
- [ ] 4. Keyboard mock buttons drive same code path as GPIO
- [ ] 5. README documents Pi deploy incl. kiosk autostart + hotspot notes
- [ ] 6. Walter Walkup on screen. Headphones, cap, mustache. Mandatory.

## Pending scope notes
- Multiple teams, >15 players (paged 5×3 grid), multiple clips per player (walkup tap / homerun long-press), touch drag-drop reorder.
