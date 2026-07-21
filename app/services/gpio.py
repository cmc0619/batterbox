"""GPIO buttons (Pi only). Calls the same playback service functions the REST
endpoints use — one code path. No-ops safely on PC (mock mode or missing
gpiozero) so the app never crashes off-Pi.
"""

import logging

from .. import config, db
from . import audio

log = logging.getLogger("batterbox.gpio")

_buttons: list = []  # keep references alive


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
    except Exception as e:  # noqa: BLE001
        log.warning("GPIO init failed (%s) — continuing without GPIO", e)
