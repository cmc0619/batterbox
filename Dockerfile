# BatterBox — single all-in-one image (FastAPI backend + static frontend)
# Runs on PC (dev, mock GPIO) and Raspberry Pi (arm64, real GPIO/audio).

FROM python:3.12-slim

# ffmpeg   — clip slicing, fades, loudnorm in the clip pipeline
# mpv      — server-side audio playback (AUDIO_BACKEND=server, used on the Pi)
# curl     — used by HEALTHCHECK and handy for debugging inside the container
# bluez    — bluetoothctl, drives the Pi's Bluetooth adapter for speaker pairing
# network-manager — nmcli, drives the host NetworkManager for the admin Wi-Fi
#            hotspot (a few dozen MB with deps, but it's the supported NM CLI)
# rfkill   — unblocking Wi-Fi/BT radios on the Pi
# swig + build-essential — ONLY needed to pip-build lgpio (gpiozero's pin
#            backend on Pi 4); purged in this same layer so the image stays lean
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg mpv curl bluez network-manager rfkill \
       swig build-essential

WORKDIR /srv

# requirements.txt includes fastapi, uvicorn, pinned yt-dlp, gpiozero + lgpio.
# lgpio compiles from source (hence swig/build-essential above); it also builds
# fine on the x86 dev image, where it simply goes unused (mock GPIO).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y swig build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY app/ app/
COPY static/ static/
COPY seed.json seed.json
COPY seed/ seed/
COPY docker-entrypoint.sh docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

# Runtime config (all overridable via compose / -e flags):
#   DATA_DIR       — SQLite DB + clips/photos/sources live here (mounted volume)
#   PORT           — HTTP port uvicorn listens on
#   MOCK_GPIO      — true = keyboard mock buttons instead of real GPIO
#   AUDIO_BACKEND  — browser = clients play audio via HTMLAudioElement;
#                    server  = mpv inside the container to the sound card
#   AUDIO_OUTPUT   — mpv/ALSA device hint ("auto" picks the default device)
ENV DATA_DIR=/data \
    PORT=8080 \
    MOCK_GPIO=true \
    AUDIO_BACKEND=browser \
    AUDIO_OUTPUT=auto

VOLUME /data

EXPOSE 8080

# PORT env is always set (default 8080); the entrypoint honors it, so the
# healthcheck must too — a hardcoded 8080 breaks when PORT is overridden.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/api/settings" || exit 1

CMD ["./docker-entrypoint.sh"]
