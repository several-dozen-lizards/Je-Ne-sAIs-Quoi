#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi
"$PYTHON" -X utf8 tools/update_jnsq.py "$@"
STATUS=$?
read -r -p "Press Return to close."
exit "$STATUS"
