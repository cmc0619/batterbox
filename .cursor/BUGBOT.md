# BatterBox — review guide for Bugbot

Walk-up song player for a youth baseball team. One Raspberry Pi 4 on a private
field LAN (usually its own hotspot), one FastAPI process, one SQLite file, a
no-build JS frontend, and a 1024×600 touchscreen. Full context: `AGENTS.md`.

Review it as an **appliance**, not a public web service.

## Intentional by design — do not file these as findings

- **No authentication or authorization anywhere.** Private LAN/hotspot appliance;
  anyone who can reach it is standing at the field. Permissive CORS
  (`allow_origins=["*"]`) is deliberate for the same reason.
- **Wi-Fi hotspot password stored and returned in plain text.** The admin page
  prefills it so the coach can read it aloud. Documented in `docs/API.md`.
- **Multiple simultaneous audio "player" clients.** Audio roles are opt-in and
  client-side; several devices (kiosk plus a spectator on a Bluetooth earpiece)
  may play the same clip, and no client can claim or revoke another's role.
  "One speaker" is an operator convention, not an invariant.
- **Permissive player/team names.** Empty, whitespace-only, and explicit-`null`
  names are accepted (a null name is stored as `""`); mid-game roster entry is
  fog-of-war and a player may be just a jersey number. `jersey_number` must be
  ≥ 0. Only a **500** on any of these is a bug.
- **One shared SQLite connection behind a lock, no ORM, no migrations
  framework.** Single-process, low-concurrency by design; schema upgrades are
  hand-written non-destructive steps in `db._migrate`.
- **Raspberry Pi 4 is the only target platform.** Pi 5 / other SBC concerns are
  out of scope.

## Worth flagging — this project's real failure modes

- **Any API/WS change whose commit does not also change `docs/API.md`.** That
  file is the binding backend↔frontend contract; drift is a defect on its own.
- **Silent fallbacks that hide hardware failure.** gpiozero without a pin
  backend silently mocks GPIO on real hardware (dead buttons, zero errors);
  anything that swallows a Pi-hardware error deserves a comment.
- **Playback state that can get stuck.** State lives only on the server and
  clients mirror it over `/ws`. A path that leaves `status: "playing"` with no
  audio (or clears it while audio continues) strands the kiosk tile and Walter.
- **Blocking the event loop** in async handlers — audio/ffmpeg/yt-dlp work
  belongs in threads. Uploads are capped at 50MB; imports decode real audio.
- **Disk leaks under `DATA_DIR`** (`clips/`, `hype/`, `sources/`, `photos/`):
  orphaned renders, abandoned import sources, stray `.tmp` files. There is a
  reconciliation sweep (`clipper.sweep_orphan_media`) — new media paths should
  stay consistent with it.
- **Values collected in one step and re-sent in a later one must be compared
  server-side**, not trusted. A clip's destination slot is recorded on the
  import job and verified at save for exactly this reason.
- **Kiosk UI regressions:** the layout is exactly 1024×600, no text below ~18px,
  huge touch targets, and nothing may depend on hover (it is a touchscreen).
  A phone-responsive path exists alongside it.
- **Offline assumptions.** The field has no internet: wavesurfer is vendored in
  `static/vendor/` and must never be loaded from a CDN at runtime; imports are
  expected to happen at home.
- **Shell scripts must stay LF.** A CRLF shebang crash-loops the container with
  a misleading "no such file or directory" (`.gitattributes` enforces this).
- **Dependency pins:** `fastapi` and `starlette` are pinned as a pair on purpose
  (Range-header and multipart DoS advisories hit this app directly). Flag a
  FastAPI bump that drags in an unpatched Starlette.

## Conventions

- No test suite exists. Do not ask for unit tests; ask for verification
  evidence against a running server (the PR body should carry it).
- `data/` is a mounted volume — its contents are never committed.
- One logical change per commit.
