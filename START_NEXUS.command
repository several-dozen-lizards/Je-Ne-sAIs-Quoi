#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi
"$PYTHON" -X utf8 shell/boot.py --session
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  echo
  echo "JNSQ could not start. The details are above."
  read -r -p "Press Return to close."
fi
exit "$STATUS"
