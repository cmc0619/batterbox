"""Environment-based configuration."""

import os


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


DATA_DIR = os.environ.get("DATA_DIR", "/data")
PORT = int(os.environ.get("PORT", "8080"))
MOCK_GPIO = _bool("MOCK_GPIO", True)
AUDIO_BACKEND = os.environ.get("AUDIO_BACKEND", "browser")  # browser | server
AUDIO_OUTPUT = os.environ.get("AUDIO_OUTPUT", "auto")
