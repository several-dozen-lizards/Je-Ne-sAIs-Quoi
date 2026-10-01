#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Install JNAIQ first with INSTALL_JNAIQ.command."
  read -r -p "Press Return to close. "
  exit 1
fi
.venv/bin/python tools/bedrock_gateway.py "$@"
gateway_status=$?
if [ "$gateway_status" -ne 0 ]; then
  read -r -p "Press Return to close. "
fi
exit "$gateway_status"
