#!/bin/bash
# BARS — double-click launcher. Starts the server and opens Chrome.
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

# Chrome currently gives the best mic + screen-share support.
open -a "Google Chrome" "http://localhost:4321" 2>/dev/null || open "http://localhost:4321"
echo "BARS is up. This window can be closed."
sleep 3
