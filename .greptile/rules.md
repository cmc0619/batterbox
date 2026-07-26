# BatterBox review rules

Private-LAN appliance: one Raspberry Pi 4 at a youth baseball field (usually on
its own hotspot, no internet), one FastAPI process, one SQLite file, a no-build
JS frontend, a 1024×600 touchscreen. Review it as an appliance, not a public
web service. Full context in `AGENTS.md`.

## Deliberate design decisions — not defects

- **Multiple simultaneous audio "player" clients are by design.** Audio roles
  are opt-in and client-side; the kiosk driving the overhead speaker and a
  spectator's phone on a Bluetooth hearing aid are meant to play the same clip
  at once. No client may claim or revoke another's role, and muting one device
  must never stop the others. "One speaker" is an operator convention, not an
  invariant to enforce.
- **End of song is the server's job, not a client's** (`server_eos` on the WS
  play event). Clients do not report `ended` when the server knows the clip
  duration — that is what keeps one listener from cutting a clip short.
- **No authentication or authorization, and permissive CORS.** Anyone who can
  reach the app is standing at the field.
- **Wi-Fi hotspot password stored and returned in plain text** so the admin
  page can prefill it and the coach can read it aloud.
- **Permissive player/team names** — empty, whitespace-only and explicit-`null`
  are accepted (null stored as `""`); a player may be just a jersey number.
  `jersey_number` must be ≥ 0. Only a 500 on any of these is a bug.
- **One shared SQLite connection behind a lock, no ORM, no migration
  framework**; hand-written non-destructive steps in `db._migrate`.
- **Raspberry Pi 4 is the only target platform.**
- **No test suite** — changes are verified against a running server, with the
  evidence in the PR body. Don't ask for unit tests.

## Worth flagging

- An API or WS change whose commit does not also update `docs/API.md` (that
  file is the binding frontend↔backend contract).
- Silent fallbacks that hide hardware failure — gpiozero mocks GPIO with no
  error when its pin backend is missing.
- Playback state that can get stuck "playing" with no audio, or clear while
  audio continues.
- Blocking the event loop in async handlers; uploads are 50MB and imports
  decode real audio.
- Disk leaks under `DATA_DIR` (`clips/`, `hype/`, `sources/`, `photos/`) —
  there is a reconciliation sweep in `clipper.sweep_orphan_media`.
- A value collected in one request and re-sent in a later one that the server
  trusts instead of comparing (clip import slots are verified at save).
- Kiosk UI regressions: exactly 1024×600, no text below ~18px, huge touch
  targets, nothing hover-dependent.
- Runtime CDN dependencies — the field is offline, so wavesurfer is vendored
  in `static/vendor/`.
- CRLF in shell scripts (a CRLF shebang crash-loops the container).
- A FastAPI bump that resolves an unpatched Starlette; the two are pinned as a
  pair on purpose.
