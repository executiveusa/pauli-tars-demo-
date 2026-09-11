#!/bin/sh
# BARS sovereign deploy (production). Usage: deploy/deploy.sh <git-sha>
# Single source of hardening truth: docker-compose.yml. Reversible via
# deploy/rollback.sh. Data and audit (receipts/budget/missions) are never
# touched by deploy or rollback unless explicitly requested.
set -eu
SHA="${1:?usage: deploy.sh <git-sha>}"
APP=${BARS_ROOT:-/opt/bars}/app
DATA=${BARS_ROOT:-/opt/bars}/data
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
cd "$APP"

echo "[deploy] snapshot data -> ${BARS_ROOT:-/opt/bars}/backups/data-$STAMP.tar.gz"
tar -czf "${BARS_ROOT:-/opt/bars}/backups/data-$STAMP.tar.gz" -C "$DATA" .

echo "[deploy] fetch + checkout $SHA"
git fetch --quiet origin
git checkout --quiet "$SHA"

echo "[deploy] build bars-sovereign:$SHA"
docker build -q -t "bars-sovereign:$SHA" . >/dev/null

echo "[deploy] preserve current SHA for rollback/audit"
if docker image inspect bars-sovereign:current >/dev/null 2>&1; then
  docker tag bars-sovereign:current bars-sovereign:rollback
fi
[ -f ${BARS_ROOT:-/opt/bars}/current.sha ] && cp ${BARS_ROOT:-/opt/bars}/current.sha ${BARS_ROOT:-/opt/bars}/previous.sha || true

docker tag "bars-sovereign:$SHA" bars-sovereign:current
echo "$SHA" > ${BARS_ROOT:-/opt/bars}/current.sha

echo "[deploy] compose restart (hardening from docker-compose.yml)"
BARS_IMAGE="bars-sovereign:$SHA" docker compose -f "$APP/docker-compose.yml" up -d --force-recreate

echo "[deploy] wait for health"
i=0
until curl -fsS -m 3 http://127.0.0.1:4321/health >/dev/null 2>&1; do
  i=$((i+1)); [ $i -gt 20 ] && { echo "[deploy] FAILED health; run deploy/rollback.sh"; exit 1; }
  sleep 2
done
echo "[deploy] OK: bars-sovereign:$SHA healthy on 127.0.0.1:4321 (sha in ${BARS_ROOT:-/opt/bars}/current.sha)"
