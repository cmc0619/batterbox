"""GPIO buttons (Pi only). Calls the same playback service functions the REST
endpoints use — one code path. No-ops safely on PC (mock mode or missing
gpiozero) so the app never crashes off-Pi.
"""

import logging

from .. import config, db
from . import audio, bluetooth

log = logging.getLogger("batterbox.gpio")

_buttons: list = []  # keep references alive
_bt_led = None  # gpiozero LED, kept alive for blink thread


def _safe(fn):
    def wrapper():
        try:
            fn()
        except Exception:  # noqa: BLE001 - a GPIO edge must never kill the app
            log.exception("GPIO handler failed")

    return wrapper


def _volume_step(delta: int) -> None:
    current = int(db.get_setting("master_volume", "80"))
    audio.set_volume(max(0, min(100, current + delta)))


def _next_batter() -> None:
    state, err = audio.play_next()
    if err:
        log.info("GPIO next: %s", err)


def _init_bt_led() -> None:
    """Pairing-indicator LED: blinks ~2Hz while Bluetooth pairing mode is
    active, off otherwise. gpio_bt_led_pin=0 disables it."""
    global _bt_led
    pin = int(db.get_setting("gpio_bt_led_pin", "26"))
    if pin == 0:
        log.info("gpio_bt_led_pin=0 — Bluetooth pairing LED disabled")
        return
    try:
        from gpiozero import LED

        _bt_led = LED(pin)
        _bt_led.off()
    except Exception as e:  # noqa: BLE001
        log.warning("BT pairing LED init failed (%s) — continuing without it", e)
        return

    def _on_pairing_change(active: bool) -> None:
        try:
            if active:
                _bt_led.blink(on_time=0.25, off_time=0.25)
            else:
                _bt_led.off()
        except Exception:  # noqa: BLE001 - a GPIO edge must never kill the app
            log.exception("BT pairing LED update failed")

    bluetooth.add_pairing_listener(_on_pairing_change)
    log.info("Bluetooth pairing LED on GPIO %d (BCM)", pin)


def init_gpio() -> None:
    if config.MOCK_GPIO:
        log.info("MOCK_GPIO=true — GPIO disabled (mock mode; frontend debug buttons call REST)")
        return
    try:
        from gpiozero import Button
    except Exception as e:  # noqa: BLE001
        log.warning("gpiozero unavailable (%s) — GPIO disabled", e)
        return
    try:
        pins = {
            "stop": int(db.get_setting("gpio_stop_pin", "17")),
            "volume_up": int(db.get_setting("gpio_volume_up_pin", "27")),
            "volume_down": int(db.get_setting("gpio_volume_down_pin", "22")),
            "next": int(db.get_setting("gpio_next_pin", "23")),
        }
        handlers = {
            "stop": _safe(audio.stop),
            "volume_up": _safe(lambda: _volume_step(5)),
            "volume_down": _safe(lambda: _volume_step(-5)),
            "next": _safe(_next_batter),
        }
        for name, pin in pins.items():
            btn = Button(pin, pull_up=True, bounce_time=0.2)
            btn.when_pressed = handlers[name]
            _buttons.append(btn)
        log.info("GPIO buttons initialized on pins %s", pins)
        _init_bt_led()
    except Exception as e:  # noqa: BLE001
        log.warning("GPIO init failed (%s) — continuing without GPIO", e)
