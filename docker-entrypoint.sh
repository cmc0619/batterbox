#!/bin/bash
# BatterBox container entrypoint.
#
# yt-dlp strategy: requirements.txt pins a known-good version (reproducible
# builds; what you tested at home is what runs at the field). On top of that,
# when the container starts WITH internet access (i.e. at home, where imports
# happen), we try to upgrade yt-dlp to the latest release so YouTube-internal
# changes are picked up without a rebuild. Offline (the field): the upgrade
# fails fast and quietly and the baked-in pin is used.
# Disable with YTDLP_AUTO_UPDATE=false.
set -u

if [ "${YTDLP_AUTO_UPDATE:-true}" = "true" ]; then
    BAKED=$(python -c 'import yt_dlp; print(yt_dlp.version.__version__)' 2>/dev/null || echo '?')
    if timeout 60 pip install -q --no-input --disable-pip-version-check --upgrade yt-dlp >/dev/null 2>&1; then
        NOW=$(python -c 'import yt_dlp; print(yt_dlp.version.__version__)' 2>/dev/null || echo '?')
        if [ "$NOW" != "$BAKED" ]; then
            echo "[entrypoint] yt-dlp auto-updated: $BAKED -> $NOW"
        else
            echo "[entrypoint] yt-dlp is current ($NOW)"
        fi
    else
        echo "[entrypoint] yt-dlp auto-update unavailable (offline?) — using baked-in $BAKED"
    fi
fi

# GPIO self-check (field debugging): with real GPIO enabled, log the active
# pin factory. Anything but lgpio on a Pi 4 means physical buttons are DEAD —
# fail loudly in `docker logs` instead of silently falling back to mock mode.
# We do not exit: kiosk/audio still work, and a dead container at the field is
# worse than a visible error.
if [ "${MOCK_GPIO:-true}" = "false" ]; then
    FACTORY=$(python -c "import gpiozero; f=gpiozero.Device.pin_factory; print(type(f).__name__ if f else 'None')" 2>/dev/null || echo 'import-error')
    echo "[gpio] pin factory: ${FACTORY}"
    if [ "${FACTORY}" != "LGPIOFactory" ]; then
        echo "[gpio] ERROR: expected LGPIOFactory on a Pi 4 — physical buttons are DEAD." >&2
        echo "[gpio] ERROR: check lgpio is installed in the image and /dev/gpiochip0 is mapped (docker-compose.pi.yml)." >&2
    fi
fi

# PORT is the port INSIDE the container (compose maps host ports onto it:
# 8080:8080 on PC, additionally 80:8080 on the Pi so phones need no port).
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
