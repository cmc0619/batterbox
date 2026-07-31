# BatterBox API Contract

This is the **binding contract** between backend and frontend. Both sides MUST implement exactly these endpoints, shapes, and behaviors. If a change is needed, update this file in the same commit.

- Static frontend served at `/` (index.html, admin.html, edit.html).
- Media files served from `/media/clips/`, `/media/photos/`, `/media/hype/`, `/media/sources/` — each mapped to the matching subdir of the `DATA_DIR` volume (`/data` in container, `./data` on host). Only these four subdirs are served; files at the volume root (the SQLite DB, mpv socket) are not reachable over HTTP.
- All JSON. All IDs are integers. Times are float seconds. Volume is int 0–100.

## WebSocket — `/ws`

Server → client JSON messages. Clients never send.

```json
{ "event": "play",    "clip_id": 3, "player_id": 7, "type": "walkup", "play_id": 12, "audio_url": "/media/clips/3.mp3", "volume": 80, "volume_boost_db": 0.0, "server_eos": true }
{ "event": "play",    "clip_id": 2, "player_id": null, "type": "hype", "play_id": 13, "audio_url": "/media/hype/2.mp3", "volume": 80, "volume_boost_db": 0.0, "server_eos": true }
{ "event": "stop" }
{ "event": "volume",  "volume": 65 }
{ "event": "warning", "message": "No audio output device found" }
{ "event": "state",   "status": "idle", "clip_id": null, "player_id": null, "type": null, "play_id": 13, "volume": 80, "audio_warning": null, "audio_url": null, "volume_boost_db": null, "duration_sec": null, "elapsed_sec": null, "server_eos": null }
{ "event": "state",   "status": "playing", "clip_id": 3, "player_id": 7, "type": "walkup", "play_id": 14, "volume": 80, "audio_warning": null, "audio_url": "/media/clips/3.mp3", "volume_boost_db": 0.0, "duration_sec": 12.0, "elapsed_sec": 4.13, "server_eos": true }
{ "event": "data_changed", "scope": "teams" }
```

`play_id` is a monotonic per-play token. Clients that report natural end-of-song echo it back (see `POST /api/playback/stop`) so a delayed `ended` from a previous clip can't stop the current one.

`audio_warning` on the `state` message is the most recent playback warning (or `null`), same as on `GET /api/playback/state` — so a client that connects **after** a warning was raised (kiosk reload, WS reconnect) can still surface it; the live `warning` event only reaches clients connected when it fired. A new play clears it.

**End of song belongs to the server.** `server_eos: true` means the server will end the play itself when the clip's own duration elapses (plus ~1s of grace for client start latency), and clients **must not** report `ended` — with several devices opted in to play, the first one to finish would otherwise stop the clip for all the others, and with no player-role client connected nothing would report at all. `server_eos: false` (a legacy row with no stored `duration_sec`) means there is no server-side end detection for that play, so a player-role client still reports `ended`. The `AUDIO_BACKEND=server` (mpv) path always reports `server_eos: false` and ends the play from mpv's own EOF instead.

`type` is `walkup`|`homerun`|`walkout` for player clips, or `hype` for hype clips — a hype play has `player_id: null` and `clip_id` = the hype clip id. The `state` message carries the same `type` semantics.

`data_changed` fires after any REST mutation of kiosk-relevant data — scope `teams` (team created/renamed/deleted or active team changed), `players` (player create/update/delete/reorder/photo, and clip create/activate/delete — those change `active_*_clip_id`), `hype` (hype clip created/deleted). It carries no payload; clients refetch what they display via REST. The kiosk refreshes its grid on this event (debounced ~300ms) and after a WS reconnect (changes made while disconnected would otherwise be missed).

Browser playback backend — client audio roles: every WS client mirrors playback state, but only a client holding the **player** role plays `audio_url` via HTMLAudioElement at `volume` (0–100 → 0–1, `volume_boost_db` via WebAudio GainNode when nonzero) and reports natural end-of-song (`POST /api/playback/stop` echoing `play_id`). Every other client is a **controller**: it sends commands and renders state but never produces sound and never reports `ended`. On `stop`, a player halts immediately (<200ms). On connect, the server sends a `state` message.

The role is **opt-in and purely client-side**: a page is a silent controller unless it is opened with `?player=1` (the kiosk launcher passes it) or its top-bar speaker toggle is on (persisted in localStorage). The role belongs to the **device**, not to one page: an explicit `?player=0`|`1` wins at page load *and is remembered*, so the launcher's instruction can't be silenced by a toggle left off, and it survives navigation from the kiosk to `admin.html` and back (only `index.html` carries the toggle, so without this the Pi's own admin page would be a silent controller and a clip tested from the touchscreen would play nothing). The stored value decides when the param is absent. **Multiple simultaneous players are allowed by design** — the Pi kiosk plus, say, a spectator listening on a phone with a Bluetooth earpiece can both play the same clip. The server enforces no exclusivity, and no client can claim or revoke another client's role: "at most one player" is an operator convention, not an invariant. A client that becomes a player while a clip is already playing **joins it in progress**: it starts the clip at `elapsed_sec` rather than waiting for the next play. That applies both to turning the toggle on mid-song (the client refetches `GET /api/playback/state`) and to a player-role page that loads or reconnects mid-song (the `state` message carries everything needed). Turning the role *off* mid-song silences that device only — it never reports a stop, because muting your own phone must not end the clip for everyone else. Ending a play is likewise not a client concern whenever `server_eos` is true (see above), so extra listeners cannot cut each other short and such a play ends on time even with no listener at all. The `server_eos: false` exception still leans on a player-role client's `ended`, so a legacy clip with no stored duration and nobody listening stays "playing" until STOP.

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

  Name validation is deliberately permissive (mid-game roster entry is fog-of-war): empty, whitespace-only, and explicit-`null` names are all accepted on create and patch — a `null` name is stored and returned as `""` (a player can be just a jersey number; this used to 500). `jersey_number` must be ≥ 0 when present (**422** otherwise); `null` clears it.
- `DELETE /api/players/{id}` → 204 (cascades clips + files)
- `POST /api/teams/{team_id}/players/reorder` `{ "player_ids": [..] }` → 204 (sets sort_order by array position). `player_ids` must be the team's **complete** roster, each id exactly once — otherwise 400 and no order change (a partial list would silently corrupt the order of omitted players).
- `POST /api/players/{id}/photo` multipart `file` (jpg/png, ≤5MB, content-checked by magic bytes — a renamed non-image 400s) → `{ "photo_url" }`. **404** if the player doesn't exist, including when it (or its team) is deleted *while the upload is being written* — the stored file is removed again, so a losing upload leaves nothing behind (`photos/` is not covered by the orphan sweep).

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
- `POST /api/clips/import/youtube` `{ "player_id", "type", "url" }` → `{ "job_id" }` (async; single video only — playlists are not expanded; downloads are size-capped at 50MB)
- `POST /api/clips/import/upload?player_id=1&type=walkup` multipart `file` (mp3/m4a, ≤50MB) → `{ "job_id" }` (async)

  **The job is bound to the slot it was imported for.** `player_id` + `type` are
  recorded on the job, and `POST /api/clips` must save into that same slot — a
  mismatch is **400**, not a silently mis-filed clip (the save's `type` used to be
  the only thing deciding where the clip landed, so a home-run import saved as
  `walkup` filed the home-run audio in the walk-up section). A hype import job is
  bound as hype: saving it via `POST /api/clips` is 400, and a player-clip job
  saved via `POST /api/hype` is 400.

  Import limits (both endpoints, and the hype equivalents): sources longer than **30 minutes** fail analysis with a clear job error (decoded PCM of unbounded sources can exhaust Pi memory), and at most **8 imports** may be pending/processing at once — the 9th returns **429** with detail.

  Body-size handling for all multipart uploads (audio import and player photo): a request whose `Content-Length` exceeds **55MB** is rejected with **413** by middleware before the body is parsed; within that, the per-endpoint caps still apply and return **400** (`file must be 50MB or smaller` for audio, `photo must be 5MB or smaller`). Chunked uploads without a `Content-Length` skip the 413 and are caught by the per-handler cap.
- `GET /api/jobs/{job_id}` →
  `{ "job_id", "status": "pending"|"processing"|"done"|"error", "detail": "",
     "duration_sec": 213.4, "suggested_start": 34.0, "suggested_end": 46.0,
     "source_audio_url": "/media/sources/abc.mp3", "peaks": [0.12, ...] }`
  (`peaks`: ~800 floats 0–1 for instant waveform render; `suggested_*` = loudest default_snippet_length window, fallback 0→length).
  **Expiry:** a `job_id` **may** be evicted ~1 hour after creation (its unsaved source file is reclaimed then). Eviction runs opportunistically on job creation and on `GET /api/jobs/{id}`, so the TTL is a lower bound, not a hard cutoff: once eviction fires, `GET /api/jobs/{expired}` → **404** and `POST /api/clips`|`/api/hype` with that id → **400** `unknown job_id`; but a job still in memory can be saved past the nominal hour (polling stops once a job is `done`, so nothing forces eviction in the meantime). Clients should stop polling on 404 and re-import. Import → trim → save takes seconds, so this only bites abandoned jobs.
- `POST /api/clips` `{ "job_id", "player_id", "type", "trim_start_sec", "trim_end_sec", "fade_in_ms", "fade_out_ms", "volume_boost_db" }` → clip (runs ffmpeg slice + fades + loudnorm → 192k MP3; sets active if first clip of that player+type). `player_id`/`type` must match the slot the job was imported for → **400** otherwise (`this import was started for player N's <type> clip, ...`). Same trim validation as PATCH (`0 ≤ trim_start_sec < trim_end_sec ≤ source duration`) → 400 on violation, checked before anything is saved. A player cascade-deleted **while the clip is being saved** (renders take seconds; the pre-render existence check can't cover them, and the row can also lose the race between its own COMMIT and the audio file being moved into place) is also **400** (`player N was deleted while the clip was rendering`) — the render is discarded and the job stays `done` with its source, so the import can be saved again for a surviving slot. Only a lost race reports 400: any other constraint failure is a real fault and surfaces as 500. Field bounds (rejected with **422**): `volume_boost_db` −24…+24 (the editor UI caps at ±12); `fade_in_ms`/`fade_out_ms` 0…60000 (the editor UI caps at 5000); all float fields reject NaN/Infinity.
- `GET /api/clips/{id}/edit_context` →
  `{ "clip": <clip object>, "source_audio_url": "/media/sources/abc.mp3", "duration_sec": 213.4, "peaks": [0.12, ...] }`
  (re-opens a saved clip in the trim editor; `duration_sec`/`peaks` describe the FULL source audio, like the job response).
  404 if clip missing; **409** if the clip has no stored source file (saved before re-edit support) or the source file no longer exists on disk.
- `PATCH /api/clips/{id}` `{ "trim_start_sec", "trim_end_sec", "fade_in_ms", "fade_out_ms", "volume_boost_db" }` (all required) → updated clip
  (re-renders from the clip's stored source with the same ffmpeg slice + fades + loudnorm → 192k MP3 pipeline; overwrites the clip's audio file via temp-file-then-move so a failed render never leaves a half-written mp3; updates `duration_sec`).
  Validation: `0 ≤ trim_start_sec < trim_end_sec ≤ source duration` → 400 on violation; `volume_boost_db` −24…+24, `fade_in_ms`/`fade_out_ms` 0…60000, and no NaN/Infinity → **422** on violation; 404 if clip missing; 409 on missing source (same as edit_context). Note: a clip saved before these bounds existed with `|volume_boost_db| > 24` can no longer be PATCHed until the boost is brought into range (the editor UI already caps at ±12, so only hand-crafted requests hit this).
- `POST /api/clips/{id}/activate` → clip (clears is_active on sibling clips of same player+type)
- `DELETE /api/clips/{id}` → 204 (removes the row + its mp3, and the trim source when nothing else references it). Deleting the **active** clip of a slot promotes the earliest remaining clip of that player+type to active in the same transaction, so a slot that still has clips never ends up with none active (deleting the last clip of a slot leaves it empty, as before)

## Hype clips

Crowd stingers ("Charge!", "Take Me Out to the Ballgame") **not tied to any player** — played from the kiosk's H mode. Same import-job/render pipeline as player clips, but keyed by a `title` (1–80 chars, required) instead of player_id/type. Rendered audio lives at `DATA_DIR/hype/<id>.mp3` → `/media/hype/<id>.mp3`.

Hype clip object:
```json
{ "id", "title": "Charge!", "source": "youtube"|"upload", "source_url": "...",
  "audio_url": "/media/hype/1.mp3",
  "duration_sec": 6.0, "trim_start_sec": 0.0, "trim_end_sec": 6.0,
  "fade_in_ms": 300, "fade_out_ms": 500, "volume_boost_db": 0.0, "created_at": "iso" }
```

- `GET /api/hype` → `[hype clip]`
- `POST /api/hype/import/youtube` `{ "title", "url" }` → `{ "job_id" }` (async, 202; same job pipeline / `GET /api/jobs/{job_id}` as player clips)
- `POST /api/hype/import/upload?title=X` multipart `file` (mp3/m4a, ≤50MB) → `{ "job_id" }` (async, 202)
- `POST /api/hype` `{ "job_id", "title", "trim_start_sec", "trim_end_sec", "fade_in_ms", "fade_out_ms", "volume_boost_db" }` → hype clip (201; same ffmpeg slice + fades + loudnorm → 192k MP3 render as player clips). The job must have come from a hype import → **400** otherwise. Same trim validation as PATCH → 400 on violation, checked before anything is saved. Same field bounds as player clips (rejected with **422**): `volume_boost_db` −24…+24, `fade_in_ms`/`fade_out_ms` 0…60000, and no NaN/Infinity.
- `GET /api/hype/{id}/edit_context` → `{ "hype": <hype clip object>, "source_audio_url", "duration_sec", "peaks" }` — same shape as the player-clip version but with `"hype"` instead of `"clip"`. 404 if missing; 409 if no stored source / source file gone.
- `PATCH /api/hype/{id}` `{ "trim_start_sec", "trim_end_sec", "fade_in_ms", "fade_out_ms", "volume_boost_db" }` (all required) → updated hype clip (re-renders from the stored source, temp-file-then-move, updates `duration_sec`). Same semantics/errors as player clips: 404 missing, 409 source gone, 400 on trim validation failure, **422** on a field bound (`volume_boost_db` −24…+24, `fade_in_ms`/`fade_out_ms` 0…60000, NaN/Infinity) — the hype PATCH shares the player-clip request model.
- `DELETE /api/hype/{id}` → 204 (removes file)

## Playback

- `POST /api/playback/play` `{ "player_id", "type" }` → state (plays active clip of that type — `walkup`|`homerun`|`walkout`; 404 if none; stops current first)
- `POST /api/playback/play_clip` `{ "clip_id" }` → state
- `POST /api/playback/play_hype` `{ "hype_id" }` → state (404 if the hype clip doesn't exist; stops current first, then broadcasts WS `play` with `type: "hype"`, `player_id: null`, `clip_id` = hype id, `audio_url`, `volume`, `volume_boost_db`). `GET /api/playback/state` and the WS `state` message report `type: "hype"` while a hype clip is playing.
- `POST /api/playback/stop` (body optional: `{ "play_id"? }`) → state (halt ≤200ms). Without a body (STOP button, GPIO): always stops. With `play_id` (the browser `ended` reporter, used only when `server_eos` was false): stops only if that play is still the current one — otherwise a no-op returning current state.
- `POST /api/playback/volume` `{ "volume": 0-100 }` → state (persisted to settings)
- `POST /api/playback/next` → state (next player in active team's batting order — wraps around — with an active walkup clip; plays it)
- `GET /api/playback/state` → `{ "status": "idle"|"playing", "clip_id", "player_id", "type", "play_id", "volume", "audio_warning": null|"...", "audio_url", "volume_boost_db", "duration_sec", "elapsed_sec", "server_eos" }` (`type` is a clip type or `"hype"`). The last five are null while idle; while playing they describe the clip well enough for a client to **join it in progress** — `elapsed_sec` is how far in the play is, measured server-side from the play broadcast, and `server_eos` says whether this play ends on the server's clock (a client joining a `server_eos: false` play must report `ended`, as on the WS `play` event).

## Bluetooth speaker pairing

Status object:
```json
{ "available": true, "pairing": false, "detail": "Bluetooth ready",
  "devices": [{ "name": "SRS-XB13", "mac": "AA:BB:CC:DD:EE:FF", "connected": true }] }
```
`available=false` (PC dev, no BlueZ/D-Bus) → `devices` is empty and `detail` is human-readable; only "unavailable" and a failed pairing start ever produce an HTTP error (400).

- `GET /api/bluetooth/status` → status object
- `POST /api/bluetooth/pairing` `{ "duration_sec": 120 }` → status (makes the Pi discoverable/pairable with auto-accept agent for duration_sec; re-posting extends the window). 400 if unavailable, **or** if the adapter could not actually be made pairable/discoverable — pairing mode is only reported active when the adapter state commands succeeded (on failure the adapter is restored best-effort and `detail` carries the bluetoothctl error).
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
- `POST /api/wifi/hotspot` `{ "ssid", "password" }` → status. Credentials are persisted **only after** nmcli succeeds — on 400 (validation failure, unavailable, or nmcli failure) the stored settings are untouched. On success the hotspot is created (any stale `batterbox` profile is deleted first) and started. If starting the new hotspot fails while the old one was running, the previous hotspot is restored best-effort from the still-stored credentials (noted in `detail`) so the Pi doesn't go dark. The response `detail` reminds that the Pi drops off its current network — admin devices must join the new SSID (browse to http://batterbox.local or http://10.42.0.1).
- `POST /api/wifi/hotspot/off` → status (400 if unavailable; a failed "connection down" on an available adapter returns 200 with the error in `detail`). NetworkManager rejoins any remembered client network (e.g. the iPhone) on its own; `detail` notes when none came up.
- `POST /api/wifi/client` `{ "ssid", "password" }` → status. "Use Wi-Fi" — the same credentials box pointed the other way: the Pi joins the named network as a client. Empty `password` = open network; otherwise WPA2 validation applies. If the `batterbox` hotspot is active it is brought down (not deleted) first — one radio can't be AP and client at once. 400 with detail on validation failure, unavailable, or nmcli connect failure; credentials are persisted **only after** a successful connect, and if the connect fails while the hotspot was up, the hotspot is brought back up best-effort (noted in `detail`) so the requesting phone can rejoin. Success `detail` reminds that admin devices must be on the target network too (http://batterbox.local).
- `POST /api/wifi/settings` `{ "ssid", "password" }` → status. Saves credentials only — **no radio change** — so it works when Wi-Fi is unavailable (configure at home on PC). 400 on validation failure; stored settings unchanged on failure.

## Settings

- `GET /api/settings` → `{ "default_snippet_length": 30, "master_volume": 80, "audio_output": "auto", "mock_gpio": true }`
- `PATCH /api/settings` partial of the above → settings. Bounds: `default_snippet_length` 3–300 (seconds), `master_volume` 0–100; an out-of-range integer → **422**. An explicit `null` for a numeric field is silently ignored (200, the setting keeps its current value) — it is never stored, because a null would serialise as the string `"None"` and break later reads.

  Environment interplay: `mock_gpio` is **read-only** — it reports the live `MOCK_GPIO` env value the GPIO layer actually booted with (a `mock_gpio` key in a PATCH is ignored). `audio_output` is patchable and persists, but a **changed** `AUDIO_OUTPUT` env value takes effect at the next boot and overwrites the stored setting (tracked via a sentinel, so an *unchanged* env never clobbers an admin-set value — previously the env was only honored on the very first boot). On the first boot of a database created before that tracking existed, the env is applied only if the stored value is still the default `auto`; any other stored value is kept (an admin's choice is indistinguishable from a stale seed there) and the env becomes the baseline for future comparisons.

## GPIO / mock buttons

GPIO handlers (real or mock) call the playback endpoints above — no separate code path. Mock mode keyboard map (implemented in frontend, calls REST): `Space` = stop, `ArrowUp/ArrowDown` = volume ±5, `N` = next batter. On-screen debug buttons visible when `mock_gpio` is true. Hype clips are played from the kiosk's on-screen H mode only — there is deliberately **no** mock-GPIO keyboard `H` shortcut.
