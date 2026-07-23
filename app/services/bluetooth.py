"""Bluetooth speaker pairing via bluetoothctl (a BlueZ D-Bus client).

On the Pi the compose file mounts the host's system D-Bus socket into the
container, so bluetoothctl inside the container drives the host's BlueZ.
On PC dev (no bluetoothctl binary / no D-Bus socket / no controller) every
function degrades to available=false with a human-readable detail — nothing
here ever raises into a router.
"""

import atexit
import logging
import os
import pty
import re
import select
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

# Long-lived bluetoothctl session that hosts the pairing agent. BlueZ agents
# live only as long as the D-Bus client that registered them, so a one-shot
# `bluetoothctl agent on` is useless — the agent dies with the process before
# any speaker gets a chance to pair. This session stays up for the whole
# pairing window.
_agent_proc: subprocess.Popen | None = None
_agent_fd: int | None = None  # pty master; a pty keeps bluetoothctl unbuffered
_agent_reader: threading.Thread | None = None
# Registration handshake: writing to the pty only proves the command was
# sent, not that BlueZ accepted the agent. The reader thread reports the
# outcome here; enter_pairing must not open the window without confirmation.
_agent_confirm = threading.Event()
_agent_confirm_ok = False  # guarded by _lock
# Bumped per spawned session; a reader thread that outlives its session's
# teardown (join timeout) must not confirm/fail a newer session's handshake.
_agent_gen = 0  # guarded by _lock

_MAC_RE = re.compile(r"^Device\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*(.*)$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x01\x02\r]")
_PAIRED_RE = re.compile(r"Device\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s+Paired:\s+yes")


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


def _set_agent_confirm(gen: int, ok: bool) -> None:
    """Record the agent-registration outcome and wake the waiter.

    Ignored when gen is stale — a reader thread from a torn-down session
    must not decide a newer session's handshake.
    """
    global _agent_confirm_ok
    with _lock:
        if gen != _agent_gen:
            return
        _agent_confirm_ok = ok
    _agent_confirm.set()


def _agent_send(cmd: str) -> bool:
    """Write one command into the live agent session. Never raises.

    The pty master is non-blocking, so this can't stall while holding _lock;
    a full buffer (stalled bluetoothctl) fails the write instead.
    """
    with _lock:
        fd = _agent_fd
        if fd is None:
            return False
        try:
            os.write(fd, (cmd + "\n").encode())
            return True
        except OSError as e:
            log.warning("write to bluetoothctl agent session failed: %s", e)
            return False


def _agent_reader_loop(fd: int, proc: subprocess.Popen, gen: int) -> None:
    """Watch the agent session's output: auto-accept prompts, trust on pair.

    With a NoInputNoOutput agent BlueZ does "just works" pairing and should
    not prompt, but some stacks still ask for service authorization — answer
    yes to any (yes/no) prompt. Devices that complete pairing get trusted so
    they can reconnect later without the pairing window being open.

    Also detects the session dying unexpectedly and closes the pairing
    window, since a window without an agent can't accept anything.
    """
    global _agent_proc, _agent_fd, _agent_reader, _pairing
    buf = ""
    trusted: set[str] = set()
    while True:
        try:
            # fd is non-blocking (so writers can never stall on it); select
            # provides the blocking wait for the read side.
            select.select([fd], [], [])
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        except (OSError, ValueError):
            break
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        buf = _ANSI_RE.sub("", buf)
        *lines, buf = buf.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            m = _PAIRED_RE.search(line)
            if m:
                mac = m.group(1).upper()
                if mac not in trusted:
                    trusted.add(mac)
                    log.info("Bluetooth device %s paired; trusting it", mac)
                    _agent_send(f"trust {mac}")
            elif "Default agent request successful" in line:
                # default-agent only succeeds with an agent registered, so
                # this one line confirms the whole registration sequence.
                log.info("bluetoothctl: %s", line)
                _set_agent_confirm(gen, ok=True)
            elif (
                "Default agent request failed" in line
                or "Failed to register agent" in line
                or "No agent is registered" in line
            ):
                log.warning("bluetoothctl: %s", line)
                _set_agent_confirm(gen, ok=False)
            elif "Agent registered" in line:
                log.info("bluetoothctl: %s", line)
        # Prompts don't end with a newline, so they sit in the partial tail.
        if "(yes/no)" in buf:
            log.info("Auto-accepting bluetoothctl prompt: %s", buf.strip())
            _agent_send("yes")
            buf = ""
        elif len(buf) > 4096:  # unterminated garbage; don't grow unbounded
            buf = buf[-1024:]
    rc = proc.poll()
    fd_to_close = None
    was_pairing = False
    with _lock:
        current = _agent_proc is proc
        if current:
            # Claim the dead session atomically: with the globals nulled and
            # _pairing flipped in the same lock hold, a concurrent
            # _start_agent can only ever spawn a fresh session — this path
            # can never tear down a live replacement.
            _agent_proc = None
            fd_to_close = _agent_fd
            _agent_fd = None
            _agent_reader = None
            was_pairing = _pairing
            _pairing = False
            _cancel_timer_locked()
    if not current:
        # _stop_agent (or a replacement start) already owns the cleanup.
        log.info("bluetoothctl agent session ended (rc=%s)", rc)
        return
    log.warning(
        "bluetoothctl agent session died unexpectedly (rc=%s); "
        "exiting pairing mode — no agent means pairing can't be accepted",
        rc,
    )
    if fd_to_close is not None:
        try:
            os.close(fd_to_close)
        except OSError:
            pass
    # Best-effort: leave the adapter as we found it.
    _run(["discoverable", "off"])
    _run(["pairable", "off"])
    if was_pairing:
        _notify_listeners(False)


def _start_agent() -> tuple[bool, str]:
    """Ensure the persistent agent session is running with its agent confirmed
    registered by BlueZ. Returns (ok, detail)."""
    global _agent_proc, _agent_fd, _agent_reader, _agent_confirm_ok, _agent_gen
    spawned = False
    with _lock:
        if _agent_proc is None or _agent_proc.poll() is not None:
            # Clean up a session that died on its own (bluetoothd restart).
            _agent_proc = None
            if _agent_fd is not None:
                try:
                    os.close(_agent_fd)
                except OSError:
                    pass
                _agent_fd = None
            try:
                master, slave = pty.openpty()
            except OSError as e:
                return False, f"could not allocate pty for bluetoothctl: {e}"
            try:
                proc = subprocess.Popen(  # noqa: S603 - fixed argv, no user input
                    ["bluetoothctl"],
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    close_fds=True,
                )
            except Exception as e:  # noqa: BLE001 - must never leak to routers
                os.close(master)
                os.close(slave)
                return False, f"could not start bluetoothctl agent session: {e}"
            os.close(slave)
            # Non-blocking master: _agent_send writes while holding _lock,
            # and a stalled bluetoothctl must fail the write (caught, logged)
            # rather than wedge every thread that needs the lock. The reader
            # side waits in select() instead of a blocking read.
            os.set_blocking(master, False)
            spawned = True
            _agent_proc = proc
            _agent_fd = master
            _agent_gen += 1
            _agent_confirm.clear()
            _agent_confirm_ok = False
            _agent_reader = threading.Thread(
                target=_agent_reader_loop,
                args=(master, proc, _agent_gen),
                daemon=True,
                name="bt-agent-reader",
            )
            _agent_reader.start()
            # bluetoothctl auto-registers a KeyboardDisplay agent on startup;
            # swap it for NoInputNoOutput so pairing is auto-accepted (no PIN).
            for cmd in ("agent off", "agent NoInputNoOutput", "default-agent"):
                _agent_send(cmd)
    # Wait for BlueZ to confirm — outside the lock so the reader can run.
    # Writing to the pty proves nothing; registration can be rejected. A
    # caller that found the session already running waits on the same event:
    # for a confirmed session it is already set and this returns instantly,
    # and a concurrent caller can't slip past an unconfirmed handshake.
    confirmed = _agent_confirm.wait(timeout=_CMD_TIMEOUT)
    with _lock:
        ok = confirmed and _agent_confirm_ok
    if not ok:
        detail = (
            "BlueZ rejected the pairing agent registration"
            if confirmed
            else "bluetoothctl did not confirm agent registration in time"
        )
        log.warning("%s; closing agent session", detail)
        _stop_agent()
        return False, detail
    if spawned:
        log.info("bluetoothctl agent session started (pid %s)", proc.pid)
        return True, "pairing agent started"
    return True, "pairing agent already running"


def _stop_agent() -> None:
    """Tear down the persistent agent session. Never raises."""
    global _agent_proc, _agent_fd, _agent_reader
    with _lock:
        proc, fd, reader = _agent_proc, _agent_fd, _agent_reader
        _agent_proc = _agent_fd = _agent_reader = None
    if proc is None:
        return
    if fd is not None:
        try:
            os.write(fd, b"quit\n")
        except OSError:
            pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            log.warning("bluetoothctl agent session did not die on kill")
    except Exception:  # noqa: BLE001
        pass
    if (
        reader is not None
        and reader is not threading.current_thread()  # reader may be the caller
        and reader.is_alive()
    ):
        reader.join(timeout=2)
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    log.info("bluetoothctl agent session stopped")


atexit.register(_stop_agent)


def _notify_listeners(active: bool) -> None:
    """Tell registered listeners (e.g. the pairing LED) the new pairing state."""
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
    """True while the pairing window is open."""
    with _lock:
        return _pairing


def get_status() -> dict:
    """Full status dict for the API: availability, pairing state, devices."""
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
    """Cancel the window-expiry timer. Caller must hold _lock."""
    global _expire_timer
    if _expire_timer is not None:
        _expire_timer.cancel()
        _expire_timer = None


def _on_expire() -> None:
    """Timer callback: the pairing window ran out."""
    log.info("Bluetooth pairing window expired")
    _set_pairing(False)


def _set_pairing(active: bool) -> None:
    """Flip pairing state; on exit also tear down the agent and adapter."""
    global _pairing
    with _lock:
        changed = _pairing != active
        _pairing = active
        _cancel_timer_locked()
    if not active:
        # Teardown runs even without a state change — the failure rollback
        # in enter_pairing lands here before _pairing was ever set True.
        _stop_agent()
        # Best-effort: leave the adapter as we found it.
        _run(["discoverable", "off"])
        _run(["pairable", "off"])
    if changed:
        # Only real transitions reach listeners: rolling back a pairing
        # start that never activated must not blink the LED "stopped".
        _notify_listeners(active)


def enter_pairing(duration_sec: int = DEFAULT_PAIRING_SEC) -> tuple[dict, str | None]:
    """Make the Pi discoverable/pairable for duration_sec. Re-entering extends."""
    available, detail = _detect()
    if not available:
        return (
            {"available": False, "pairing": False, "detail": detail, "devices": []},
            detail,
        )
    # The agent must outlive this request: it stays registered only while its
    # bluetoothctl session lives, and it is what auto-accepts the pairing.
    # No agent → advertised auto-pairing can't work → fail the request.
    ok, agent_detail = _start_agent()
    if not ok:
        err = f"could not start pairing agent: {agent_detail}"
        log.warning(err)
        status = get_status()
        status["detail"] = err
        return status, err
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
            # Leave everything as we found it: kill the agent session and
            # roll the adapter back (best-effort, inside _set_pairing).
            _set_pairing(False)
            status = get_status()
            status["detail"] = err
            return status, err
    global _expire_timer, _pairing
    with _lock:
        # The agent must still be alive when the window commits: the adapter
        # commands above block for seconds, and the session can die in that
        # gap (bluetoothd restart). Checked in the same lock hold that flips
        # _pairing so the reader's death-cleanup can't be overwritten.
        agent_alive = _agent_proc is not None and _agent_proc.poll() is None
        if agent_alive:
            _pairing = True
            _cancel_timer_locked()
            _expire_timer = threading.Timer(duration_sec, _on_expire)
            _expire_timer.daemon = True
            _expire_timer.start()
    if not agent_alive:
        err = "pairing agent died during adapter setup"
        log.warning(err)
        _set_pairing(False)  # rolls the adapter back; agent is already gone
        status = get_status()
        status["detail"] = err
        return status, err
    log.info("Bluetooth pairing mode on for %ss", duration_sec)
    _notify_listeners(True)
    return get_status(), None


def exit_pairing() -> dict:
    """Close the pairing window early (idempotent)."""
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
