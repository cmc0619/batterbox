# BatterBox

**Big league music for big league moments.**

BatterBox is a walk-up song player for youth baseball, hosted on a Raspberry Pi in the dugout. Tap a player's face on the touchscreen, their walk-up song blasts over the PA. Long-press for the home-run clip. Walter Walkup — headphones, cap, mustache — is the mascot, and he takes his job seriously.

## What it does

- **Kiosk grid** — 1024×600 touchscreen layout, one big tile per player, photo + name + number. Tap = walk-up clip, long-press (600ms) = home-run clip. Instant switch, STOP in under 200ms.
- **Multiple teams** — switch the active team per game; each team has its own batting order. Touch drag-and-drop reorder in the admin screen.
- **Clip workflow** — import from YouTube or upload mp3/m4a, trim on a waveform editor, add fades and volume boost, loudness-normalized to 192k MP3.
- **Physical buttons** — wire real buttons to the Pi's GPIO pins for STOP / next batter / volume, or use the on-screen/keyboard mock buttons.
- **Works offline at the field** — phones on the dugout Wi-Fi hotspot can queue songs; no internet needed once clips are imported.

## Screenshots

| Kiosk grid (1024×600 touchscreen) | Admin (teams, roster, drag-to-reorder) |
| --- | --- |
| ![Kiosk grid](docs/screenshots/kiosk-grid.png) | ![Admin](docs/screenshots/admin.png) |

| Clip editor (waveform trim) | Phone layout |
| --- | --- |
| ![Clip editor](docs/screenshots/clip-editor.png) | ![Phone](docs/screenshots/phone.png) |

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

3. **Kiosk display** (full-screen touchscreen UI on the Pi's display):

   **No KDE, Gnome, or any desktop environment is needed — and none is used.** The "window system" is one of two tiny options; both just put Chromium's kiosk window on the HDMI touchscreen. There is no Qt app and nothing to write in Qt — Chromium *is* the UI runtime, pointed at `http://localhost:8080`.

   **Option A — Raspberry Pi OS Lite + cage (recommended, lightest).** [cage](https://github.com/cage-kiosk/cage) is a Wayland kiosk compositor: it is the entire "window manager", runs exactly one app full-screen, and is made for appliances like this. Touch works out of the box via libinput.

   ```bash
   sudo apt update && sudo apt install -y cage chromium
   # autologin to a console on boot:
   sudo raspi-config   # System Options → Boot / Auto Login → Console Autologin
   # launch the kiosk when the console session starts:
   echo 'if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then exec cage -- /home/pi/batterbox/kiosk/start-kiosk.sh; fi' >> ~/.bash_profile
   ```

   On boot: Pi logs itself in on tty1 → cage starts → `start-kiosk.sh` waits for the container and execs Chromium full-screen. Boot-to-music on a Pi 5 is well under a minute.

   **Option B — Raspberry Pi OS with desktop** (what you'd use anyway for other things): keep the stock Wayland/X session and autostart the kiosk into it:

   ```bash
   mkdir -p ~/.config/autostart
   cp kiosk/batterbox-kiosk.desktop ~/.config/autostart/
   # edit ~/.config/autostart/batterbox-kiosk.desktop if the repo isn't at /home/pi/batterbox
   ```

   Either way the kiosk script waits for the app to answer on port 8080, then opens Chromium full-screen. Audio plays through the browser out the 3.5mm jack / HDMI / USB DAC — plug your speaker/PA into the Pi.

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
| `YTDLP_AUTO_UPDATE` | `true` | `true` = upgrade yt-dlp to latest at container start when online        |

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
- **YouTube imports fail** — YouTube changes its internals regularly; yt-dlp answers with frequent releases. Two layers of defense:
  1. **At every container start with internet access, BatterBox auto-upgrades yt-dlp to the latest release** (check `docker compose logs app` for the `[entrypoint] yt-dlp` line). Offline (the field), it silently keeps the baked-in version. Disable with `YTDLP_AUTO_UPDATE=false`.
  2. The pin in `requirements.txt` is the known-good fallback baked into the image — what you tested at home is what runs at the field. If imports break even after the auto-update, bump the pin and rebuild:

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
