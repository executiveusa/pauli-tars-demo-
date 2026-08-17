#!/bin/bash
# BARS — double-click launcher. Starts the cockpit and its Terabithia adapter.
cd "$(dirname "$0")"

if [ ! -f config.json ]; then
  echo "No config.json found."
  echo "Copy config.example.json to config.json and add the provider keys you intend to use."
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

# Already running? Just open the UI.
if lsof -tnP -iTCP:4321 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "BARS is already running — opening the cockpit."
else
  echo "Launching BARS on http://localhost:4321 ..."
  nohup python3 server.py > server.log 2>&1 &
  sleep 2
fi

# Terabithia gets a narrow fleet contract on a separate loopback-only port.
if lsof -tnP -iTCP:4324 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Terabithia adapter is already running."
else
  echo "Launching BARS Terabithia adapter on http://127.0.0.1:4324 ..."
  nohup python3 terabithia_adapter.py > terabithia-adapter.log 2>&1 &
  sleep 1
fi

# Chrome currently gives the best mic + screen-share support.
open -a "Google Chrome" "http://localhost:4321" 2>/dev/null || open "http://localhost:4321"
echo "BARS is up. This window can be closed."
sleep 3
