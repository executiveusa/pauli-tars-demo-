#!/bin/sh
# BARS rollback: restore the previous image and the newest data snapshot.
set -eu
PREV=$(docker image inspect bars-sovereign:rollback --format '{{.Id}}' 2>/dev/null || true)
[ -n "$PREV" ] || { echo "[rollback] no previous image tagged"; exit 1; }

SNAP=$(ls -1t /opt/bars/backups/data-*.tar.gz 2>/dev/null | head -1 || true)
if [ -n "$SNAP" ]; then
  echo "[rollback] restore data snapshot $SNAP"
  tar -xzf "$SNAP" -C /opt/bars/data
fi

echo "[rollback] restart bars on previous image"
docker rm -f bars >/dev/null 2>&1 || true
docker run -d --name bars --restart unless-stopped \
  -p 127.0.0.1:4321:4321 \
  -v /opt/bars/data:/data \
  --env-file /opt/bars/.env \
  --memory 512m --cpus 0.75 --pids-limit 128 \
  --read-only --tmpfs /tmp:size=64m,mode=1777 \
  --security-opt no-new-privileges:true --cap-drop ALL \
  bars-sovereign:rollback >/dev/null

i=0
until curl -fsS -m 3 http://127.0.0.1:4321/health >/dev/null 2>&1; do
  i=$((i+1)); [ $i -gt 20 ] && { echo "[rollback] FAILED health"; exit 1; }
  sleep 2
done
echo "[rollback] OK: previous image healthy"
