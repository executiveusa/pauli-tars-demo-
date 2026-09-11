#!/bin/sh
# BARS rollback. Default: swap to the previous image ONLY - post-deploy data,
# receipts, budget ledger and missions are preserved untouched.
# --with-data: stop the service, then ATOMICALLY replace data with the
# snapshot linked to the previous deployment (never an overlay extract).
set -eu
ROOT=${BARS_ROOT:-/opt/bars}
APP=$ROOT/app
cd "$APP"

PREV_SHA=""
[ -f $ROOT/previous.sha ] && PREV_SHA=$(cat $ROOT/previous.sha)
docker image inspect bars-sovereign:rollback >/dev/null 2>&1 || { echo "[rollback] no previous image tagged"; exit 1; }

if [ "${1:-}" = "--with-data" ]; then
  # the snapshot linked to the deployment being restored
  SNAP=""
  [ -f $ROOT/previous.snapshot ] && SNAP=$(cat $ROOT/previous.snapshot)
  [ -n "$SNAP" ] && [ -f "$SNAP" ] || { echo "[rollback] no deployment-linked snapshot found"; exit 1; }
  echo "[rollback] stopping service before atomic data replace"
  docker compose -f "$APP/docker-compose.yml" stop 2>/dev/null || true
  TMPD=$(mktemp -d $ROOT/.data-restore-XXXXXX)
  tar -xzf "$SNAP" -C "$TMPD"
  OLD=$(mktemp -du $ROOT/.data-old-XXXXXX)
  mv $ROOT/data "$OLD"
  mv "$TMPD" $ROOT/data
  echo "[rollback] data replaced atomically from $SNAP (old data at $OLD)"
else
  echo "[rollback] image-only: post-deploy data/receipts/audit preserved"
fi

CUR=$(cat $ROOT/current.sha 2>/dev/null || echo unknown)
case "$PREV_SHA" in
  ""|unknown) echo "[rollback] FATAL: no previous deployment SHA recorded"; exit 1;;
esac
echo "$PREV_SHA" | grep -qiE '^[0-9a-f]{40}$' || { echo "[rollback] FATAL: previous.sha must be exactly 40 lowercase hex chars, got '$PREV_SHA'"; exit 2; }
echo "[rollback] rolling back from $CUR to $PREV_SHA"

docker tag bars-sovereign:rollback bars-sovereign:current
# relink for REPEATED rollback: current <- previous, previous <- rolled-back-from
[ -f $ROOT/current.sha ] && cp $ROOT/current.sha $ROOT/previous.sha || true
[ -f $ROOT/current.snapshot ] && cp $ROOT/current.snapshot $ROOT/previous.snapshot || true
echo "$PREV_SHA" > $ROOT/current.sha
export BARS_GIT_SHA="$PREV_SHA"

BARS_IMAGE=bars-sovereign:rollback docker compose -f "$APP/docker-compose.yml" up -d --force-recreate

i=0
while :; do
  GOT=$(curl -fsS -m 3 http://127.0.0.1:4321/health 2>/dev/null | grep -o '"sha": *"[0-9a-f]*"' | grep -o '[0-9a-f]\{40\}' || true)
  [ "$GOT" = "$PREV_SHA" ] && break
  i=$((i+1)); [ $i -gt 20 ] && { echo "[rollback] FAILED: /health reports '${GOT:-none}', expected $PREV_SHA"; exit 1; }
  sleep 2
done
echo "[rollback] OK: $PREV_SHA healthy and /health verifies (rolled back from $CUR)"
