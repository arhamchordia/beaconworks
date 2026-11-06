#!/bin/sh
# One-time setup for the beaconworks-triage plugin, run by you in a terminal, not by Codex:
#   1. a private Python environment in ~/.beaconworks/venv, with the plugin's requirements
#   2. who you are, in ~/.beaconworks/caller (a name from server/access.json)
# Usage: sh plugins/beaconworks-triage/server/setup.sh support.lead
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CALLER="$1"
if [ -z "$CALLER" ] || ! grep -q "\"$CALLER\":" "$ROOT/server/access.json"; then
  echo "Usage: sh $0 CALLER, where CALLER is one of the names in $ROOT/server/access.json" >&2
  exit 2
fi
mkdir -p "$HOME/.beaconworks"
if [ ! -x "$HOME/.beaconworks/venv/bin/python3" ]; then
  python3 -m venv "$HOME/.beaconworks/venv"
fi
"$HOME/.beaconworks/venv/bin/python3" -m pip install -q -r "$ROOT/requirements.txt"
printf '%s\n' "$CALLER" > "$HOME/.beaconworks/caller"
echo "beaconworks-triage is set up: Python in $HOME/.beaconworks/venv, caller $CALLER"
