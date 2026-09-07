# Usability Bug Fixes Design

## Goal

Fix the ten user-visible reliability problems selected in the September 2026
code review without adding security hardening, a test framework, new runtime
dependencies, or broad defensive abstractions.

## Scope

1. Deferred browser-audio startup must not restart sound after STOP, mute, or a
   newer play.
2. Kiosk and Admin team loads must not display players from the wrong team.
3. Admin must allow a player with a jersey number and an empty name.
4. A player-role client must be able to join the current play after missing a
   newer play while its WebSocket was disconnected.
5. An intentionally configured 12-second default snippet must survive restart.
6. In server-audio mode, mpv—not a browser listener—owns end-of-song, while
   browser listeners receive the existing one-second completion grace.
7. Bare ALSA `hw:` and `plughw:` settings must be translated to mpv's
   `alsa/...` device syntax, and examples must show the correct form.
8. Wi-Fi radio-changing operations must run one at a time and stop when current
   connection state cannot be read; they must not guess that the hotspot is
   inactive.
9. Admin Add Team and Add Player actions must ignore a second tap while their
   first request is pending.
10. The Pi kiosk must use the port-80 compose mapping by default and keep
    waiting when application startup exceeds the initial warning threshold.

## Exclusions

- No protections aimed at hostile clients, including chunked-request limits.
- No additional yt-dlp download limits.
- No generalized request coordinator, state-version protocol, or retry library.
- No committed automated-test framework.
- No unrelated API validation or cleanup work.

## Design

### Browser playback

`static/js/ws.js` will keep one monotonically increasing playback generation.
STOP, role-off, and every new source increment it. A deferred metadata callback
captures its generation and does nothing if another transition has occurred.
This is the smallest state comparison that fixes sound restarting after STOP
and stale seeks affecting a newer clip.

Joining the current play will compare the generation captured before the REST
request with the generation when it resolves. It will no longer reject a newer
server play merely because the last WebSocket play ID is older.

### Team and roster UI

Kiosk team loading will fetch the selected roster before committing the team
name and tiles. If a changed team's roster fails, old-team tiles will be
cleared.

Admin player loads will capture the requested team ID and a sequence number;
only the latest selected team's response may render. Add Team and Add Player
buttons will be disabled only for the duration of their own request. Player
creation will accept an empty name when a valid jersey number is present, and
editing will submit the actual trimmed name rather than restoring the old one.

### Persisted settings

The historical `12 -> 30` startup update will be removed. Fresh databases
already seed `30`, and installations that have previously upgraded have already
received the old migration. This allows the public 3–300 setting range,
including 12, to remain stable across restart without adding schema machinery.

### mpv playback

Server-backend plays will advertise server-owned end-of-song so current clients
do not report `ended`. The server will also ignore automatic, play-ID-bearing
stop reports for any server-owned play, covering older cached clients.

When mpv reaches EOF, playback state will remain current for the existing
one-second grace and then stop unless superseded or manually stopped. Manual
STOP remains immediate.

Bare `hw:` and `plughw:` audio-output values will be prefixed with `alsa/`
before invoking mpv. Documentation will recommend copying an identifier from
`mpv --audio-device=help`.

### Wi-Fi operations

A module-level lock will serialize hotspot start, hotspot stop, and client
connect. Active-connection discovery will return success separately from the
connection map. A failed discovery aborts radio-changing work with its existing
human-readable error instead of treating an unknown state as “hotspot off.”

### Kiosk startup

The Pi launcher default URL will be `http://localhost`, matching the Pi compose
port-80 mapping. `BATTERBOX_URL` remains the override. Crossing the configured
wait threshold will log a warning and continue checking rather than opening
Chromium's non-retrying connection-error page.

## Verification

The repository's no-test-suite policy remains in effect. Verification will use:

- focused one-off Node/Python scripts for deferred audio, settings persistence,
  Wi-Fi serialization/state failure, and duplicate-submit behavior;
- a running no-Docker FastAPI server for REST/WebSocket regressions;
- headless Chromium/CDP for kiosk and Admin race scenarios;
- mpv and nmcli stubs for server-audio and radio transitions;
- static parsing and shell syntax checks.

`docs/API.md` will change in the same commit as mpv WebSocket semantics. README
and Pi compose comments will change with the audio-device and kiosk guidance.
