#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Je Ne Sais Quoi needs Python 3.10 through 3.12."
  echo "Install Python 3.12 from https://www.python.org/downloads/macos/"
  open "https://www.python.org/downloads/macos/"
  read -r -p "Press Return to close."
  exit 1
fi
python3 tools/setup_jnsq_macos.py "$@"
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  read -r -p "Press Return to close."
fi
exit "$STATUS"
