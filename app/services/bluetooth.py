"""Bluetooth speaker pairing via bluetoothctl (a BlueZ D-Bus client).

On the Pi the compose file mounts the host's system D-Bus socket into the
container, so bluetoothctl inside the container drives the host's BlueZ.
On PC dev (no bluetoothctl binary / no D-Bus socket / no controller) every
function degrades to available=false with a human-readable detail — nothing
here ever raises into a router.
"""

import logging
import os
import re
import shutil
import subprocess
import threading

log = logging.getLogger("batterbox.bluetooth")

DEFAULT_PAIRING_SEC = 120
_CMD_TIMEOUT = 5  # seconds; bluetoothctl answers fast or not at all
_CONNECT_TIMEOUT = 15  # connecting to a speaker can take a few seconds

_lock = threading.RLock()
_expire_timer: threading.Timer | None = None
_pairing = False
_pairing_listeners: list = []  # fn(active: bool), e.g. the GPIO pairing LED

_MAC_RE = re.compile(r"^Device\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*(.*)$")


def _run(args: list[str], timeout: int = _CMD_TIMEOUT) -> tuple[bool, str]:
    """Run bluetoothctl non-interactively. Never raises."""
    try:
        proc = subprocess.run(
            ["bluetoothctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "bluetoothctl not installed"
    except subprocess.TimeoutExpired:
        return False, f"bluetoothctl {' '.join(args)} timed out"
    except Exception as e:  # noqa: BLE001 - must never leak to routers
        return False, str(e)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out


def _detect() -> tuple[bool, str]:
    """(available, human-readable detail). Cheap enough to run per status poll."""
    if shutil.which("bluetoothctl") is None:
        return False, "bluetoothctl is not installed in this container (bluez package missing)"
    addr = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS", "")
    sock = None
    if addr:
        m = re.search(r"unix:path=([^,;]+)", addr)
        sock = m.group(1) if m else None
    else:
        sock = "/run/dbus/system_bus_socket"
    if sock and not os.path.exists(sock):
        return False, (
            "system D-Bus socket not found — on the Pi, mount "
            "/run/dbus/system_bus_socket into the container (docker-compose.pi.yml)"
        )
    ok, out = _run(["show"])
    if "No default controller available" in out:
        return False, "no Bluetooth controller available (host Bluetooth is off or missing)"
    if not ok:
        return False, f"bluetoothctl show failed: {out or 'no output'}"
    return True, "Bluetooth ready"


def _list_devices() -> list[dict]:
    """Paired devices with current connected state. Defensive parsing."""
    ok, out = _run(["devices"])
    devices = []
    if not ok:
        return devices
    for line in out.splitlines():
        m = _MAC_RE.match(line.strip())
        if not m:
            continue
        mac = m.group(1).upper()
        name = m.group(2).strip() or mac
        connected = False
        ok2, info = _run(["info", mac])
        if ok2:
            for iline in info.splitlines():
                iline = iline.strip()
                if iline.startswith("Connected:"):
                    connected = iline.split(":", 1)[1].strip().lower() == "yes"
        devices.append({"name": name, "mac": mac, "connected": connected})
    return devices


def _notify_listeners(active: bool) -> None:
    for fn in list(_pairing_listeners):
        try:
            fn(active)
        except Exception:  # noqa: BLE001 - a listener must never kill pairing
            log.exception("pairing listener failed")


def add_pairing_listener(fn) -> None:
    """Register fn(active: bool), called whenever pairing mode toggles."""
    with _lock:
        _pairing_listeners.append(fn)


def is_pairing() -> bool:
    with _lock:
        return _pairing


def get_status() -> dict:
    available, detail = _detect()
    if not available:
        return {"available": False, "pairing": False, "detail": detail, "devices": []}
    return {
        "available": True,
        "pairing": is_pairing(),
        "detail": detail,
        "devices": _list_devices(),
    }


def _cancel_timer_locked() -> None:
    global _expire_timer
    if _expire_timer is not None:
        _expire_timer.cancel()
        _expire_timer = None


def _on_expire() -> None:
    log.info("Bluetooth pairing window expired")
    _set_pairing(False)


def _set_pairing(active: bool) -> None:
    global _pairing
    with _lock:
        _pairing = active
        _cancel_timer_locked()
    if not active:
        # Best-effort: leave the adapter as we found it.
        _run(["discoverable", "off"])
        _run(["pairable", "off"])
    _notify_listeners(active)


def enter_pairing(duration_sec: int = DEFAULT_PAIRING_SEC) -> tuple[dict, str | None]:
    """Make the Pi discoverable/pairable for duration_sec. Re-entering extends."""
    available, detail = _detect()
    if not available:
        return (
            {"available": False, "pairing": False, "detail": detail, "devices": []},
            detail,
        )
    # Best-effort only: each _run is a one-shot bluetoothctl process, so the
    # agent it registers dies with it (known limitation — a persistent agent
    # needs a long-lived bluetoothctl session; untested without Pi hardware).
    for args in (["agent", "on"], ["default-agent"]):
        ok, out = _run(args)
        if not ok:
            log.warning("bluetoothctl %s failed: %s", " ".join(args), out)
    # Adapter state commands are required: if the adapter never became
    # discoverable/pairable, "pairing mode" would be a lie — fail the request
    # instead of flashing a Pairing UI nothing can see.
    for args in (
        ["pairable", "on"],
        # 0 = never auto-expire inside BlueZ; our own timer owns the window.
        ["discoverable-timeout", "0"],
        ["discoverable", "on"],
    ):
        ok, out = _run(args)
        if not ok:
            err = f"bluetoothctl {' '.join(args)} failed: {out or 'no output'}"
            log.warning(err)
            # Leave the adapter as we found it (best-effort).
            _run(["discoverable", "off"])
            _run(["pairable", "off"])
            status = get_status()
            status["detail"] = err
            return status, err
    global _expire_timer, _pairing
    with _lock:
        _pairing = True
        _cancel_timer_locked()
        _expire_timer = threading.Timer(duration_sec, _on_expire)
        _expire_timer.daemon = True
        _expire_timer.start()
    log.info("Bluetooth pairing mode on for %ss", duration_sec)
    _notify_listeners(True)
    return get_status(), None


def exit_pairing() -> dict:
    if is_pairing():
        log.info("Bluetooth pairing mode off")
    _set_pairing(False)
    return get_status()


def connect(mac: str) -> tuple[dict, str | None]:
    """Connect to a known (paired or scanned) device by MAC."""
    available, detail = _detect()
    if not available:
        return (
            {"available": False, "pairing": False, "detail": detail, "devices": []},
            detail,
        )
    ok, out = _run(["connect", mac], timeout=_CONNECT_TIMEOUT)
    status = get_status()
    # bluetoothctl exits 0 even on failure; the output is the truth.
    if ok and "Connection successful" in out:
        log.info("Connected to Bluetooth device %s", mac)
        return status, None
    err = f"connect to {mac} failed: {out or 'no response from bluetoothctl'}"
    log.warning(err)
    status["detail"] = err
    return status, err
