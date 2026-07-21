# BatterBox

**Big league music for big league moments.**

BatterBox is a walk-up song player for youth baseball, hosted on a Raspberry Pi in the dugout. Tap a player's face on the touchscreen, their walk-up song blasts over the PA. Long-press for the home-run clip. Walter Walkup — headphones, cap, mustache — is the mascot, and he takes his job seriously.

## What it does

- **Kiosk grid** — 1024×600 touchscreen layout, one big tile per player, photo + name + number. Tap = walk-up clip, long-press (600ms) = home-run clip. Instant switch, STOP in under 200ms.
- **Multiple teams** — switch the active team per game; each team has its own batting order. Touch drag-and-drop reorder in the admin screen.
- **Clip workflow** — import from YouTube or upload mp3/m4a, trim on a waveform editor, add fades and volume boost, loudness-normalized to 192k MP3.
- **Physical buttons** — wire real buttons to the Pi's GPIO pins for STOP / next batter / volume, or use the on-screen/keyboard mock buttons.
- **Works offline at the field** — phones on the dugout Wi-Fi hotspot can queue songs; no internet needed once clips are imported.

## Run it on your PC (dev / demo)

Requires Docker Desktop. That's all.

```bash
docker compose up --build
```

Open http://localhost:8080 — the grid loads seeded with two demo teams (Sandlot Sluggers and Dugout Demons). Audio plays through your PC's browser; GPIO is mocked.

Mock GPIO keyboard shortcuts (same code path as real GPIO):

| Key   | Action            |
| ----- | ----------------- |
| Space | Stop              |
| ↑ / ↓ | Volume ±5         |
| N     | Next batter       |

Debug buttons for the same actions appear on screen when mock GPIO is on.

## The clip workflow

Do this at home, on Wi-Fi — YouTube imports need internet, and the field won't have any.

1. Open http://localhost:8080/admin.html — create your team, add players (names + jersey numbers), snap photos or upload them.
2. For each player, paste a YouTube URL (or upload an mp3/m4a) and pick walk-up or home-run.
3. BatterBox downloads the audio in the background and suggests the loudest 12-second window.
4. Open the trim editor: drag the start/end handles on the waveform, preview, set fade in/out and volume boost if a track is quieter than the rest.
5. Save. The clip is sliced, faded, loudness-normalized, and live on the grid.
6. Set the batting order by dragging tiles in admin.

At the field, everything plays from local disk. No internet, no problem.

## Deploy to the Raspberry Pi

Target: Raspberry Pi OS 64-bit (Bookworm or later), Pi 4 or 5 recommended.

1. **Install Docker:**

   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER   # log out and back in after this
   ```

2. **Clone and start:**

   ```bash
   git clone <your-repo-url> batterbox
   cd batterbox
   docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build
   ```

   The first build takes a while on a Pi — go warm up the infield. The app comes up on port 8080 and restarts on reboot automatically (`unless-stopped`).

3. **Kiosk autostart** (full-screen touchscreen UI on the Pi's display):

   ```bash
   mkdir -p ~/.config/autostart
   cp kiosk/batterbox-kiosk.desktop ~/.config/autostart/
   # edit ~/.config/autostart/batterbox-kiosk.desktop if the repo isn't at /home/pi/batterbox
   ```

   On the next login the kiosk script waits for the app to answer on port 8080, then opens Chromium full-screen. Audio plays through the browser out the 3.5mm jack or HDMI — plug your speaker/PA into the Pi.

4. **Wi-Fi hotspot** (phones in the dugout): configure the Pi as a hotspot — NetworkManager makes this one command:

   ```bash
   sudo nmcli device wifi hotspot ifname wlan0 ssid BatterBox password "take me out to the ballgame"
   ```

   Phones join the `BatterBox` network and browse to the Pi's IP (typically `http://10.42.0.1:8080` — check with `ip addr show wlan0`). The grid and admin pages work fine on a phone screen.

### Audio: browser vs server backend

Default is `AUDIO_BACKEND=browser`: the kiosk Chromium on the Pi plays the sound. Zero Docker audio config needed.

If you want the Pi headless (no browser, phones only), set `AUDIO_BACKEND=server` in `docker-compose.pi.yml` — mpv inside the container plays directly to ALSA via the mapped `/dev/snd`. You may need `AUDIO_OUTPUT` (e.g. `plughw:1,0` for a USB dongle) if auto picks the wrong device.

## Configuration

All env vars, settable in `docker-compose.yml` / `.env` / shell:

| Var             | Default   | What it does                                                            |
| --------------- | --------- | ----------------------------------------------------------------------- |
| `PORT`          | `8080`    | HTTP port                                                               |
| `DATA_DIR`      | `/data`   | SQLite DB + clips/photos/sources (mounted to `./data` on the host)      |
| `MOCK_GPIO`     | `true`    | `true` = keyboard/on-screen mock buttons; `false` = real GPIO (Pi)      |
| `AUDIO_BACKEND` | `browser` | `browser` = clients play audio; `server` = mpv in-container to ALSA     |
| `AUDIO_OUTPUT`  | `auto`    | ALSA device hint for server playback (e.g. `plughw:1,0`)                |

Playback settings (default snippet length, master volume) are also editable live in admin.

## GPIO wiring

Physical buttons call the same playback API as the touchscreen — one code path, no surprises. Wire momentary push buttons between GPIO pins and GND (uses internal pull-ups, active-low). Suggested defaults, BCM numbering:

| Button      | BCM pin  | Physical pin |
| ----------- | -------- | ------------ |
| Stop        | GPIO 17  | 11           |
| Next batter | GPIO 27  | 13           |
| Volume up   | GPIO 22  | 15           |
| Volume down | GPIO 23  | 16           |

`/dev/gpiomem` is mapped into the container by `docker-compose.pi.yml` — no privileged container needed. Keep wires away from the audio cable; GPIO noise on a cheap speaker wire sounds like a swarm of bees.

## Troubleshooting

- **"No audio output device found" warning** — the app couldn't find a sound device. With `browser` backend this is just informational (browsers play their own audio); with `server` backend, check that `/dev/snd` is mapped (Pi compose file), the speaker is plugged in before container start, and try setting `AUDIO_OUTPUT` explicitly (`aplay -l` on the Pi lists devices).
- **YouTube imports fail** — YouTube changes its internals regularly; yt-dlp is pinned in `requirements.txt` for exactly this reason. Bump the pin to the latest release:

  ```bash
  pip index versions yt-dlp          # or check https://github.com/yt-dlp/yt-dlp/releases
  # edit requirements.txt, then:
  docker compose up --build
  ```

- **Nothing downloads at the field** — expected. YouTube import needs internet. Import at home; the field run is fully offline.
- **Chromium shows a "restore pages?" bubble** — the kiosk script already passes `--disable-session-crashed-bubble` and `--incognito`; if you see it anyway you killed power mid-write. It's harmless; tap through once.
- **Container logs** — `docker compose logs -f app`.

## Repo layout

- `app/` — FastAPI backend (routers, clip pipeline, playback, GPIO)
- `static/` — no-build JS SPA (kiosk grid, admin, trim editor, Walter Walkup)
- `data/` — runtime data (gitignored)
- `docs/API.md` — binding backend↔frontend API contract
- `kiosk/` — Pi kiosk launcher + autostart desktop entry
