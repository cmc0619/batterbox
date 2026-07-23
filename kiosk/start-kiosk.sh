#!/usr/bin/env bash
# BatterBox kiosk launcher — runs on the Raspberry Pi (host, not Docker).
#
# Waits for the BatterBox container to answer on localhost:8080, then opens
# Chromium full-screen (kiosk) tuned for the 1024x600 official touchscreen.
# No desktop environment (KDE/Gnome) is required — pick one display path:
#
# A) Raspberry Pi OS Lite + cage (recommended, no desktop at all):
#      sudo apt install -y cage chromium squeekboard
#      sudo raspi-config  # System Options → Boot / Auto Login → Console Autologin
#      ~/.bash_profile:
#        if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
#          exec cage -- /home/pi/batterbox/kiosk/start-kiosk.sh
#        fi
#    (cage IS the entire window system — a tiny Wayland kiosk compositor that
#     runs this one script full-screen; Chromium speaks Wayland to it natively.
#     squeekboard = on-screen keyboard, started below if installed.)
#
# B) Raspberry Pi OS with desktop (autostart into the stock session):
#      mkdir -p ~/.config/autostart
#      cp kiosk/batterbox-kiosk.desktop ~/.config/autostart/batterbox-kiosk.desktop
#    (The .desktop file sits next to this script; edit the Exec= path inside it
#     if you cloned the repo somewhere other than /home/pi/batterbox.)

set -u

URL="${BATTERBOX_URL:-http://localhost:8080}"
MAX_WAIT="${BATTERBOX_KIOSK_WAIT:-120}"   # seconds to wait for the app

echo "[batterbox-kiosk] waiting for ${URL} (up to ${MAX_WAIT}s)..."
elapsed=0
until curl -fsS --max-time 2 "${URL}/api/settings" >/dev/null 2>&1; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [ "${elapsed}" -ge "${MAX_WAIT}" ]; then
        echo "[batterbox-kiosk] app did not come up in ${MAX_WAIT}s — starting browser anyway"
        break
    fi
done
echo "[batterbox-kiosk] app is up after ~${elapsed}s"

# Find a Chromium binary: Raspberry Pi OS names it chromium-browser on older
# releases, chromium on newer ones.
CHROMIUM=""
for bin in chromium-browser chromium chromium-browser-stable google-chrome; do
    if command -v "${bin}" >/dev/null 2>&1; then
        CHROMIUM="${bin}"
        break
    fi
done

if [ -z "${CHROMIUM}" ]; then
    echo "[batterbox-kiosk] ERROR: no Chromium found (tried chromium-browser, chromium)." >&2
    echo "[batterbox-kiosk] Install it with: sudo apt install chromium-browser" >&2
    exit 1
fi

# On-screen keyboard: with no physical keyboard attached, text fields (Wi-Fi
# SSID/password, player names, YouTube URLs) are dead ends without one.
# squeekboard is a Wayland OSK that pops up when a text input gains focus and
# hides when it loses it — works under cage and the Pi OS desktop session.
# Install on the Pi with: sudo apt install squeekboard
OSK_PID=""
if command -v squeekboard >/dev/null 2>&1; then
    echo "[batterbox-kiosk] starting squeekboard on-screen keyboard"
    squeekboard &
    OSK_PID=$!
    trap '[ -n "${OSK_PID}" ] && kill "${OSK_PID}" 2>/dev/null' EXIT
fi

echo "[batterbox-kiosk] launching ${CHROMIUM} in kiosk mode at ${URL}"
exec "${CHROMIUM}" \
    --kiosk "${URL}" \
    --window-size=1024,600 \
    --start-fullscreen \
    --incognito \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-infobars \
    --disable-translate \
    --disable-features=TranslateUI \
    --autoplay-policy=no-user-gesture-required \
    --check-for-update-interval=31536000 \
    --overscroll-history-navigation=0 \
    --disable-pinch \
    --touch-events=enabled
