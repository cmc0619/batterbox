"""Wi-Fi hotspot control via nmcli (a NetworkManager D-Bus client).

On the Pi the compose file mounts the host's system D-Bus socket into the
container, so nmcli inside the container drives the host's NetworkManager —
the Pi can broadcast its own "BatterBox" hotspot instead of joining a phone's
tethered hotspot (some plans charge for tethering). On PC dev (no nmcli
binary / no D-Bus socket / NM not running) every function degrades to
available=false with a human-readable detail — nothing here ever raises into
a router (validation uses ValueError internally and is caught at the boundary).

The hotspot password is stored in plain text in the settings table and
returned to the admin UI on purpose: this is a private-LAN appliance with no
auth, and the coach needs to read the password aloud to the dugout.
"""

import logging
import os
import re
import shutil
import subprocess

from .. import db

log = logging.getLogger("batterbox.wifi")

IFNAME = "wlan0"
HOTSPOT_CON_NAME = "batterbox"  # NetworkManager connection profile name
DEFAULT_SSID = "BatterBox"
DEFAULT_PASSWORD = "bigleague1"
_CMD_TIMEOUT = 10  # seconds; nmcli answers fast or not at all
_ENABLE_TIMEOUT = 30  # bringing up an AP (scan/channel negotiation) can take a while


def _run(args: list[str], timeout: int = _CMD_TIMEOUT) -> tuple[bool, str]:
    """Run nmcli non-interactively. Never raises."""
    try:
        proc = subprocess.run(
            ["nmcli", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "nmcli not installed"
    except subprocess.TimeoutExpired:
        return False, f"nmcli {' '.join(args)} timed out"
    except Exception as e:  # noqa: BLE001 - must never leak to routers
        return False, str(e)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out


def _detect() -> tuple[bool, str]:
    """(available, human-readable detail). Cheap enough to run per status poll."""
    if shutil.which("nmcli") is None:
        return False, "nmcli is not installed in this container (network-manager package missing)"
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
    ok, out = _run(["general", "status"])
    if not ok:
        if "not running" in out.lower():
            return False, "NetworkManager is not running on the host"
        return False, f"nmcli general status failed: {out or 'no output'}"
    return True, "NetworkManager ready"


def _validate(ssid: str, password: str) -> None:
    """WPA2 rules. Raises ValueError — nmcli must never be called with garbage."""
    ssid = (ssid or "").strip()
    if not 1 <= len(ssid) <= 32:
        raise ValueError("SSID must be 1–32 characters")
    if not 8 <= len(password or "") <= 63:
        raise ValueError("password must be 8–63 characters (WPA2 rule)")
    if any(ord(c) < 0x20 or ord(c) > 0x7E for c in password):
        raise ValueError("password must be printable ASCII (WPA2 rule)")


def _active_connections() -> dict[str, str]:
    """{connection name: device} for active connections. Defensive parsing:
    tolerates empty output, blank lines, and ':' in names (nmcli -t escapes
    them as '\\:'; device is always the last field)."""
    ok, out = _run(["-t", "-f", "NAME,DEVICE", "connection", "show", "--active"])
    conns: dict[str, str] = {}
    if not ok:
        return conns
    for line in out.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, device = line.rsplit(":", 1)
        if device:
            conns[name.replace("\\:", ":")] = device
    return conns


def _wlan_ip() -> str | None:
    """IPv4 address of wlan0 (no netmask), or None. Tolerates weird output."""
    ok, out = _run(["-t", "-f", "IP4.ADDRESS", "device", "show", IFNAME])
    if not ok:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("IP4.ADDRESS") and ":" in line:
            val = line.split(":", 1)[1].strip()
            if val:
                return val.split("/", 1)[0]
    return None


def get_status() -> dict:
    """Full status object per docs/API.md. ssid/password are the STORED
    settings (form prefill); mode/hotspot_active/ip describe live state."""
    status = {
        "available": False,
        "detail": "",
        "mode": "unknown",
        "hotspot_active": False,
        "ssid": db.get_setting("wifi_ssid", DEFAULT_SSID),
        "password": db.get_setting("wifi_password", DEFAULT_PASSWORD),
        "ip": None,
    }
    available, detail = _detect()
    if not available:
        status["detail"] = detail
        return status
    status["available"] = True
    conns = _active_connections()
    if conns.get(HOTSPOT_CON_NAME):
        status["mode"] = "hotspot"
        status["hotspot_active"] = True
        status["ip"] = _wlan_ip()
        status["detail"] = (
            f"Hotspot ON — SSID '{status['ssid']}'"
            + (f" ({status['ip']})" if status["ip"] else "")
            + " — join it and open http://batterbox.local"
        )
        return status
    client = next(
        (name for name, dev in conns.items() if dev == IFNAME and name != HOTSPOT_CON_NAME),
        None,
    )
    if client:
        status["mode"] = "client"
        status["ip"] = _wlan_ip()
        status["detail"] = (
            f"Client mode — connected to '{client}'"
            + (f" ({status['ip']})" if status["ip"] else "")
        )
        return status
    status["mode"] = "offline"
    status["detail"] = f"Wi-Fi available but {IFNAME} is not connected to any network"
    return status


def save_settings(ssid: str, password: str) -> tuple[dict, str | None]:
    """Persist credentials only — no radio change, works when Wi-Fi is
    unavailable (configure at home on PC). Validation happens BEFORE the save,
    so a bad payload never overwrites good settings."""
    ssid = (ssid or "").strip()
    try:
        _validate(ssid, password)
    except ValueError as e:
        return get_status(), str(e)
    db.set_setting("wifi_ssid", ssid)
    db.set_setting("wifi_password", password)
    log.info("Wi-Fi hotspot settings saved (SSID '%s')", ssid)
    return get_status(), None


def _create_hotspot(ssid: str, password: str) -> tuple[bool, str]:
    return _run(
        [
            "device", "wifi", "hotspot",
            "ifname", IFNAME,
            "con-name", HOTSPOT_CON_NAME,
            "ssid", ssid,
            "password", password,
            "band", "bg",  # 2.4GHz — best phone compatibility
        ],
        timeout=_ENABLE_TIMEOUT,
    )


def enable_hotspot(ssid: str, password: str) -> tuple[dict, str | None]:
    """Validate → check availability → switch radios → save. Credentials are
    persisted only after nmcli succeeds, so a 400 never overwrites good
    settings; if the new hotspot fails while the old one was running, the old
    hotspot is restored (best-effort) so the Pi doesn't go dark."""
    ssid = (ssid or "").strip()
    try:
        _validate(ssid, password)
    except ValueError as e:
        return get_status(), str(e)
    available, detail = _detect()
    if not available:
        return get_status(), detail
    prev_ssid = db.get_setting("wifi_ssid", DEFAULT_SSID)
    prev_password = db.get_setting("wifi_password", DEFAULT_PASSWORD)
    was_active = bool(_active_connections().get(HOTSPOT_CON_NAME))
    # Replace any previous profile so re-enabling with new credentials works.
    ok, out = _run(["connection", "delete", "id", HOTSPOT_CON_NAME])
    if not ok:
        log.info("no stale '%s' connection to delete (%s)", HOTSPOT_CON_NAME, out)
    ok, out = _create_hotspot(ssid, password)
    if ok:
        db.set_setting("wifi_ssid", ssid)
        db.set_setting("wifi_password", password)
        log.info("Wi-Fi hotspot '%s' enabled on %s", ssid, IFNAME)
        status = get_status()
        status["detail"] = (
            f"Hotspot '{ssid}' is ON — the Pi left its previous Wi-Fi. "
            f"Admin devices must join '{ssid}' and reopen "
            "http://batterbox.local (or http://10.42.0.1)."
        )
        return status, None
    err = f"nmcli hotspot failed: {out or 'no response from nmcli'}"
    log.warning(err)
    if was_active:
        # The old profile was deleted above; recreate it from the still-stored
        # previous credentials so admins keep a way onto the box.
        ok2, out2 = _create_hotspot(prev_ssid, prev_password)
        if ok2:
            log.info("restored previous hotspot '%s' after failure", prev_ssid)
            err += f" — previous hotspot '{prev_ssid}' restored"
        else:
            log.warning("failed to restore previous hotspot: %s", out2)
            err += " — and restoring the previous hotspot failed"
    status = get_status()
    status["detail"] = err
    return status, err


def connect_client(ssid: str, password: str) -> tuple[dict, str | None]:
    """Join an existing network as a client ("Use Wi-Fi" — the same SSID/password
    box as the hotspot, pointed the other way). Drops the batterbox hotspot first
    if it's up — one radio can't be AP and client at once. An empty password
    means an open network (no password arg passed to nmcli)."""
    ssid = (ssid or "").strip()
    if not 1 <= len(ssid) <= 32:
        return get_status(), "SSID must be 1–32 characters"
    if password:  # empty = open network; otherwise WPA2 rules apply
        try:
            _validate(ssid, password)
        except ValueError as e:
            return get_status(), str(e)
    available, detail = _detect()
    if not available:
        return get_status(), detail
    was_hotspot = bool(_active_connections().get(HOTSPOT_CON_NAME))
    if was_hotspot:
        # One radio can't be AP and client at once. Down (not delete) the
        # profile so it can be brought straight back up if the connect fails.
        ok, out = _run(["connection", "down", "id", HOTSPOT_CON_NAME])
        if not ok:
            log.warning("failed to down hotspot before client connect: %s", out)
    args = ["device", "wifi", "connect", ssid, "ifname", IFNAME]
    if password:
        args += ["password", password]
    ok, out = _run(args, timeout=_ENABLE_TIMEOUT)
    if ok:
        # Persist only after success — a typo'd password must not overwrite
        # the credentials of the hotspot people are actually using.
        db.set_setting("wifi_ssid", ssid)
        db.set_setting("wifi_password", password)
        log.info("Wi-Fi client connected to '%s' on %s", ssid, IFNAME)
        status = get_status()
        status["detail"] = (
            f"Joined '{ssid}' as a client"
            + (f" ({status['ip']})" if status["ip"] else "")
            + f". Admin devices must be on '{ssid}' too — open http://batterbox.local."
        )
        return status, None
    err = f"nmcli connect failed: {out or 'no response from nmcli'}"
    log.warning(err)
    if was_hotspot:
        # Bring the hotspot back so the requesting phone can rejoin —
        # otherwise a wrong password leaves the Pi unreachable in the field.
        ok2, out2 = _run(
            ["connection", "up", "id", HOTSPOT_CON_NAME], timeout=_ENABLE_TIMEOUT
        )
        if ok2:
            log.info("restored hotspot after failed client connect")
            err += " — hotspot restored, rejoin it to retry"
        else:
            log.warning("failed to restore hotspot: %s", out2)
            err += " — and restoring the hotspot failed"
    status = get_status()
    status["detail"] = err
    return status, err


def disable_hotspot() -> tuple[dict, str | None]:
    """Take the hotspot down. NetworkManager rejoins any remembered client
    network (e.g. the iPhone) on its own; detail notes when none came up."""
    available, detail = _detect()
    if not available:
        return get_status(), detail
    ok, out = _run(["connection", "down", "id", HOTSPOT_CON_NAME])
    status = get_status()
    if status["hotspot_active"]:
        err = f"failed to stop hotspot: {out or 'no response from nmcli'}"
        log.warning(err)
        status["detail"] = err
        return status, err
    if not ok:
        log.info("hotspot was not active (%s)", out)
    if status["mode"] == "client":
        log.info("Wi-Fi hotspot off — reconnected to a client network")
        status["detail"] = f"Hotspot off. {status['detail']}"
    else:
        status["detail"] = (
            "Hotspot off. NetworkManager will rejoin any remembered Wi-Fi "
            "network (e.g. the iPhone hotspot) on its own; if none comes up, "
            "reconnect manually (sudo nmcli device wifi connect ...)."
        )
    return status, None
