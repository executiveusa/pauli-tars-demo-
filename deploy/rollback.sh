#!/bin/sh
# BARS rollback. Default: swap to the previous image ONLY - post-deploy data,
# receipts, budget ledger and missions are preserved untouched. Pass
# --with-data to also restore the newest pre-deploy data snapshot (that
# discards post-deploy state; use only when the new code corrupted data).
set -eu
APP=${BARS_ROOT:-/opt/bars}/app
cd "$APP"

PREV_SHA=""
[ -f ${BARS_ROOT:-/opt/bars}/previous.sha ] && PREV_SHA=$(cat ${BARS_ROOT:-/opt/bars}/previous.sha)
docker image inspect bars-sovereign:rollback >/dev/null 2>&1 || { echo "[rollback] no previous image tagged"; exit 1; }

if [ "${1:-}" = "--with-data" ]; then
  SNAP=$(ls -1t ${BARS_ROOT:-/opt/bars}/backups/data-*.tar.gz 2>/dev/null | head -1 || true)
  [ -n "$SNAP" ] || { echo "[rollback] no data snapshot found"; exit 1; }
  echo "[rollback] stopping service before data restore"
  docker compose -f "$APP/docker-compose.yml" stop 2>/dev/null || true
  echo "[rollback] ALSO restoring data snapshot $SNAP (post-deploy data lost)"
  tar -xzf "$SNAP" -C ${BARS_ROOT:-/opt/bars}/data
else
  echo "[rollback] image-only: post-deploy data/receipts/audit preserved"
fi

CUR=$(cat ${BARS_ROOT:-/opt/bars}/current.sha 2>/dev/null || echo unknown)
echo "$CUR" > ${BARS_ROOT:-/opt/bars}/rolled-back-from.sha
echo "[rollback] rolling back from $CUR to ${PREV_SHA:-previous image}"

docker tag bars-sovereign:rollback bars-sovereign:current
[ -n "$PREV_SHA" ] && echo "$PREV_SHA" > ${BARS_ROOT:-/opt/bars}/current.sha

BARS_IMAGE=bars-sovereign:rollback docker compose -f "$APP/docker-compose.yml" up -d --force-recreate

i=0
until curl -fsS -m 3 http://127.0.0.1:4321/health >/dev/null 2>&1; do
  i=$((i+1)); [ $i -gt 20 ] && { echo "[rollback] FAILED health"; exit 1; }
  sleep 2
done
echo "[rollback] OK: previous image healthy (rolled back from $CUR, recorded in rolled-back-from.sha)"
