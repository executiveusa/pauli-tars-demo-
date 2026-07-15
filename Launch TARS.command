#!/bin/bash
# TARS — double-click launcher. Starts the server and opens Chrome.
cd "$(dirname "$0")"

if [ ! -f config.json ]; then
  echo "⚠️  No config.json found."
  echo "    Duplicate config.example.json → rename to config.json → paste your Anthropic key."
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

# already running? just open the UI
if lsof -tnP -iTCP:4321 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "TARS is already running — opening the cockpit."
else
  echo "Launching TARS on http://localhost:4321 ..."
  nohup python3 server.py > server.log 2>&1 &
  sleep 2
fi

# Chrome gives the best mic + screen-share support
open -a "Google Chrome" "http://localhost:4321" 2>/dev/null || open "http://localhost:4321"
echo "TARS is up. This window can be closed."
sleep 3
