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

# PORT is the port INSIDE the container (compose maps host ports onto it:
# 8080:8080 on PC, additionally 80:8080 on the Pi so phones need no port).
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
