#!/bin/sh
# Ariadne launcher for Linux. make_shortcut.py writes a desktop entry that runs
# this file; you can also run it from a terminal. Arguments go straight through
# to app.py, so "./start.sh --port 8080" works.
cd "$(dirname "$0")" || exit 1

PY=""
command -v python3 >/dev/null 2>&1 && PY=python3
[ -z "$PY" ] && command -v python >/dev/null 2>&1 && PY=python
if [ -z "$PY" ]; then
  echo
  echo "  Python 3 was not found. Install it, then run this again."
  echo
  read -r _ 2>/dev/null
  exit 1
fi

if ! "$PY" -c "import flask, PIL, cryptography" >/dev/null 2>&1; then
  echo "Installing what it needs (Flask, Pillow and cryptography), just this once..."
  "$PY" -m pip install --quiet -r requirements.txt || {
    echo "  Could not install the requirements. Try: $PY -m pip install -r requirements.txt"
    read -r _ 2>/dev/null
    exit 1
  }
fi

exec "$PY" app.py "$@"
