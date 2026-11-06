#!/bin/sh
# Starts the triage MCP server for Codex. Codex runs this from its installed copy of the
# plugin and sets PLUGIN_ROOT. The Python environment lives outside the plugin, in
# ~/.beaconworks/venv, made once by server/setup.sh, so it survives plugin updates.
# Anything this script prints goes to stderr: stdout belongs to MCP messages.
ROOT="${PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON="$HOME/.beaconworks/venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "beaconworks-triage: no Python environment at $PYTHON. Run once: sh $ROOT/server/setup.sh CALLER" >&2
  exit 1
fi
exec "$PYTHON" "$ROOT/server/triage_server.py"
