#!/usr/bin/env bash
# Clip Studio launcher for macOS / Linux: sets everything up the first time, then starts the app.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "  Python 3.11 or newer is needed."
  echo "  macOS:  install it from https://www.python.org/downloads/  (or: brew install python@3.12)"
  echo ""
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo ""
  echo "  ffmpeg not found."
  if [ "$(uname)" = "Darwin" ]; then
    echo "  Install it with:  brew install ffmpeg      (Homebrew: https://brew.sh)"
  else
    echo "  Install it with your package manager, e.g.:  sudo apt install ffmpeg"
  fi
  echo "  Then run this script again."
  echo ""
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating a private Python environment in .venv …"
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Installing Clip Studio's packages (a few minutes the first time) …"
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.installed
else
  # Sites change often; a fresh yt-dlp keeps downloads working.
  .venv/bin/python -m pip install -q --upgrade "yt-dlp[default]" deno >/dev/null 2>&1 || true
fi

exec .venv/bin/python -m clipstudio "$@"
