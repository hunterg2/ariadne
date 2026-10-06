#!/bin/sh
# Ariadne launcher for macOS: double-click it in Finder. make_shortcut.py puts
# a wrapper for it on the desktop. Arguments go straight through to app.py.
# macOS may ask once whether you trust it: right-click, Open, then Open again.
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

if ! "$PY" -c "import flask, PIL" >/dev/null 2>&1; then
  echo "Installing what it needs (Flask and Pillow), just this once..."
  "$PY" -m pip install --quiet -r requirements.txt || {
    echo "  Could not install the requirements. Try: $PY -m pip install -r requirements.txt"
    read -r _ 2>/dev/null
    exit 1
  }
fi

exec "$PY" app.py "$@"
