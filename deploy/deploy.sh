#!/bin/sh
# BARS sovereign deploy (production). Usage: deploy/deploy.sh <git-sha>
# Reversible: the previous image tag and data snapshot are kept for rollback.sh.
set -eu
SHA="${1:?usage: deploy.sh <git-sha>}"
APP=/opt/bars/app
DATA=/opt/bars/data
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

echo "[deploy] snapshot data -> /opt/bars/backups/data-$STAMP.tar.gz"
tar -czf "/opt/bars/backups/data-$STAMP.tar.gz" -C "$DATA" .

echo "[deploy] fetch + checkout $SHA"
git -C "$APP" fetch --quiet origin
git -C "$APP" checkout --quiet "$SHA"

echo "[deploy] build bars-sovereign:$SHA"
docker build -q -t "bars-sovereign:$SHA" "$APP" >/dev/null
docker tag "bars-sovereign:$SHA" bars-sovereign:previous-candidate 2>/dev/null || true

echo "[deploy] record previous image for rollback"
docker tag bars-sovereign:current bars-sovereign:rollback 2>/dev/null || true
docker tag "bars-sovereign:$SHA" bars-sovereign:current
echo "$SHA" > /opt/bars/current.sha

echo "[deploy] restart container"
docker rm -f bars >/dev/null 2>&1 || true
docker run -d --name bars --restart unless-stopped \
  -p 127.0.0.1:4321:4321 \
  -v /opt/bars/data:/data \
  --env-file /opt/bars/.env \
  --env BARS_GIT_SHA="$SHA" \
  --memory 512m --cpus 0.75 --pids-limit 128 \
  --read-only --tmpfs /tmp:size=64m,mode=1777 \
  --security-opt no-new-privileges:true --cap-drop ALL \
  bars-sovereign:current >/dev/null

echo "[deploy] wait for health"
i=0
until curl -fsS -m 3 http://127.0.0.1:4321/health >/dev/null 2>&1; do
  i=$((i+1)); [ $i -gt 20 ] && { echo "[deploy] FAILED health; run deploy/rollback.sh"; exit 1; }
  sleep 2
done
echo "[deploy] OK: bars-sovereign:$SHA healthy on 127.0.0.1:4321"
