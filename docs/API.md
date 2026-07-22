# BatterBox API Contract

This is the **binding contract** between backend and frontend. Both sides MUST implement exactly these endpoints, shapes, and behaviors. If a change is needed, update this file in the same commit.

- Static frontend served at `/` (index.html, admin.html, edit.html).
- Media files (clips, photos) served from `/media/...` mapped to the `DATA_DIR` volume (`/data` in container, `./data` on host).
- All JSON. All IDs are integers. Times are float seconds. Volume is int 0–100.

## WebSocket — `/ws`

Server → client JSON messages. Clients never send.

```json
{ "event": "play",    "clip_id": 3, "player_id": 7, "type": "walkup", "audio_url": "/media/clips/3.mp3", "volume": 80, "volume_boost_db": 0.0 }
{ "event": "stop" }
{ "event": "volume",  "volume": 65 }
{ "event": "warning", "message": "No audio output device found" }
{ "event": "state",   "status": "idle", "clip_id": null, "player_id": null, "type": null, "volume": 80 }
```

Browser playback backend: on `play`, clients play `audio_url` via HTMLAudioElement at `volume` (0–100 → 0–1), applying `volume_boost_db` via WebAudio GainNode when nonzero. On `stop`, halt immediately (<200ms). On connect, server sends a `state` message.

## Teams

- `GET /api/teams` → `[{ "id", "name", "sort_order", "player_count" }]`
- `POST /api/teams` `{ "name" }` → team
- `PATCH /api/teams/{id}` `{ "name" }` → team
- `DELETE /api/teams/{id}` → 204 (cascades players + clips + files)
- `GET /api/teams/active` → `{ "team_id" }`
- `POST /api/teams/active` `{ "team_id" }` → `{ "team_id" }`

## Players

- `GET /api/teams/{team_id}/players` → ordered by `sort_order`:
  `[{ "id", "team_id", "name", "jersey_number", "photo_url" | null, "sort_order",
      "absent": false,
      "active_walkup_clip_id" | null, "active_homerun_clip_id" | null,
      "active_walkout_clip_id" | null }]`

  `absent: true` hides the player from the kiosk grid and phone list and skips
  them in next-batter, but they stay in the roster (admin always lists them).
- `POST /api/teams/{team_id}/players` `{ "name", "jersey_number" }` → player
- `PATCH /api/players/{id}` `{ "name"?, "jersey_number"?, "absent"? }` → player
- `DELETE /api/players/{id}` → 204 (cascades clips + files)
- `POST /api/teams/{team_id}/players/reorder` `{ "player_ids": [..] }` → 204 (sets sort_order by array position)
- `POST /api/players/{id}/photo` multipart `file` (jpg/png, ≤5MB) → `{ "photo_url" }`

## Clips

Clip object (`type`: `walkup` = batter walk-up, `homerun` = home-run celebration,
`walkout` = pitcher entrance/walk-out):
```json
{ "id", "player_id", "type": "walkup"|"homerun"|"walkout", "is_active": true,
  "source": "youtube"|"upload", "source_url": "...", "audio_url": "/media/clips/12.mp3",
  "duration_sec": 12.0, "trim_start_sec": 34.5, "trim_end_sec": 46.5,
  "fade_in_ms": 300, "fade_out_ms": 500, "volume_boost_db": 0.0, "created_at": "iso" }
```

- `GET /api/players/{id}/clips` → `[clip]`
- `POST /api/clips/import/youtube` `{ "player_id", "type", "url" }` → `{ "job_id" }` (async)
- `POST /api/clips/import/upload?player_id=1&type=walkup` multipart `file` (mp3/m4a) → `{ "job_id" }` (async)
- `GET /api/jobs/{job_id}` →
  `{ "job_id", "status": "pending"|"processing"|"done"|"error", "detail": "",
     "duration_sec": 213.4, "suggested_start": 34.0, "suggested_end": 46.0,
     "source_audio_url": "/media/sources/abc.mp3", "peaks": [0.12, ...] }`
  (`peaks`: ~800 floats 0–1 for instant waveform render; `suggested_*` = loudest default_snippet_length window, fallback 0→length)
- `POST /api/clips` `{ "job_id", "player_id", "type", "trim_start_sec", "trim_end_sec", "fade_in_ms", "fade_out_ms", "volume_boost_db" }` → clip (runs ffmpeg slice + fades + loudnorm → 192k MP3; sets active if first clip of that player+type)
- `GET /api/clips/{id}/edit_context` →
  `{ "clip": <clip object>, "source_audio_url": "/media/sources/abc.mp3", "duration_sec": 213.4, "peaks": [0.12, ...] }`
  (re-opens a saved clip in the trim editor; `duration_sec`/`peaks` describe the FULL source audio, like the job response).
  404 if clip missing; **409** if the clip has no stored source file (saved before re-edit support) or the source file no longer exists on disk.
- `PATCH /api/clips/{id}` `{ "trim_start_sec", "trim_end_sec", "fade_in_ms", "fade_out_ms", "volume_boost_db" }` (all required) → updated clip
  (re-renders from the clip's stored source with the same ffmpeg slice + fades + loudnorm → 192k MP3 pipeline; overwrites the clip's audio file via temp-file-then-move so a failed render never leaves a half-written mp3; updates `duration_sec`).
  Validation: `0 ≤ trim_start_sec < trim_end_sec ≤ source duration`, fades ≥ 0 → 400 on violation; 404 if clip missing; 409 on missing source (same as edit_context).
- `POST /api/clips/{id}/activate` → clip (clears is_active on sibling clips of same player+type)
- `DELETE /api/clips/{id}` → 204 (removes file; clears active flag)

## Playback

- `POST /api/playback/play` `{ "player_id", "type" }` → state (plays active clip of that type — `walkup`|`homerun`|`walkout`; 404 if none; stops current first)
- `POST /api/playback/play_clip` `{ "clip_id" }` → state
- `POST /api/playback/stop` → state (halt ≤200ms)
- `POST /api/playback/volume` `{ "volume": 0-100 }` → state (persisted to settings)
- `POST /api/playback/next` → state (next player in active team's batting order — wraps around — with an active walkup clip; plays it)
- `GET /api/playback/state` → `{ "status": "idle"|"playing", "clip_id", "player_id", "type", "volume", "audio_warning": null|"..." }`

## Bluetooth speaker pairing

Status object:
```json
{ "available": true, "pairing": false, "detail": "Bluetooth ready",
  "devices": [{ "name": "SRS-XB13", "mac": "AA:BB:CC:DD:EE:FF", "connected": true }] }
```
`available=false` (PC dev, no BlueZ/D-Bus) → `devices` is empty and `detail` is human-readable; only "unavailable" ever produces an HTTP error (400).

- `GET /api/bluetooth/status` → status object
- `POST /api/bluetooth/pairing` `{ "duration_sec": 120 }` → status (makes the Pi discoverable/pairable with auto-accept agent for duration_sec; re-posting extends the window; 400 if unavailable)
- `POST /api/bluetooth/pairing/stop` → status (ends pairing mode early)
- `POST /api/bluetooth/connect` `{ "mac": "AA:BB:CC:DD:EE:FF" }` → status (connect attempt to a known device; 400 if unavailable, otherwise a failed attempt returns 200 with the error in `detail`)

## Wi-Fi hotspot

The Pi can broadcast its own hotspot (NetworkManager connection con-name `batterbox`) instead of joining a phone's tethered hotspot.

Status object:
```json
{ "available": true, "detail": "Hotspot ON — SSID 'BatterBox' (10.42.0.1) — join it and open http://batterbox.local",
  "mode": "hotspot", "hotspot_active": true, "ssid": "BatterBox", "password": "bigleague1", "ip": "10.42.0.1" }
```
`mode` ∈ `"hotspot"|"client"|"offline"|"unknown"`. `ssid`/`password` are the **stored** settings (returned in plain text for form prefill — private-LAN appliance, no auth; the coach reads the password aloud). `mode`/`hotspot_active`/`ip` describe **live** state. `available=false` (PC dev — no nmcli/D-Bus/NetworkManager) → mode `"unknown"`, `hotspot_active` false, `ip` null, human-readable `detail`; defaults (`BatterBox` / `bigleague1`) are still present.

- `GET /api/wifi/status` → status object (always 200)
- `POST /api/wifi/hotspot` `{ "ssid", "password" }` → status. Validation (ssid 1–32 chars, password 8–63 printable ASCII) and availability are checked **before** anything is saved — on 400 the stored settings are untouched. On success the credentials are persisted and the hotspot is created (any stale `batterbox` profile is deleted first) and started. 400 with detail on validation failure, unavailable, or nmcli failure. The response `detail` reminds that the Pi drops off its current network — admin devices must join the new SSID (browse to http://batterbox.local or http://10.42.0.1).
- `POST /api/wifi/hotspot/off` → status (400 if unavailable; a failed "connection down" on an available adapter returns 200 with the error in `detail`). NetworkManager rejoins any remembered client network (e.g. the iPhone) on its own; `detail` notes when none came up.
- `POST /api/wifi/settings` `{ "ssid", "password" }` → status. Saves credentials only — **no radio change** — so it works when Wi-Fi is unavailable (configure at home on PC). 400 on validation failure; stored settings unchanged on failure.

## Settings

- `GET /api/settings` → `{ "default_snippet_length": 30, "master_volume": 80, "audio_output": "auto", "mock_gpio": true }`
- `PATCH /api/settings` partial of the above → settings

## GPIO / mock buttons

GPIO handlers (real or mock) call the playback endpoints above — no separate code path. Mock mode keyboard map (implemented in frontend, calls REST): `Space` = stop, `ArrowUp/ArrowDown` = volume ±5, `N` = next batter. On-screen debug buttons visible when `mock_gpio` is true.
