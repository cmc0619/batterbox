#!/usr/bin/env bash
# BatterBox — Cursor Cloud Agent install (no-Docker backend, per AGENTS.md).
# Idempotent: safe to re-run. Installs the system packages the pinned Python
# deps need, then builds/refreshes the repo-root .venv from requirements.txt.
set -euo pipefail

cd "$(dirname "$0")/.."

# System packages:
#   python3.12-venv       — the base image ships python3.12 without ensurepip
#   swig + build-essential — lgpio (gpiozero's Pi pin backend) builds from source
#   ffmpeg                — clip pipeline (slice/fade/loudnorm), always exercised
#   mpv                   — AUDIO_BACKEND=server playback (Pi option; harmless here)
if command -v sudo >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends \
    python3.12-venv swig build-essential ffmpeg mpv
else
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    python3.12-venv swig build-essential ffmpeg mpv
fi

# Create the venv only if it's missing or broken, then (re)install deps. pip is
# idempotent, so re-running just reconciles the venv with requirements.txt.
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "BatterBox install complete — run: DATA_DIR=./data MOCK_GPIO=true .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080"
