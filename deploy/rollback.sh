#!/bin/sh
# BARS rollback. Runs the IMMUTABLE image of the previous deployment
# (bars-sovereign:$PREV_SHA), relinks current/previous + their deployment
# snapshots, records rolled-back-from, and verifies /health reports the exact
# restored SHA from image-baked provenance.
# Default: image-only - post-deploy data/receipts/audit preserved.
# --with-data: stop the service, then ATOMICALLY replace data with the
# snapshot linked to the restored deployment (never an overlay extract).
set -eu
ROOT=${BARS_ROOT:-/opt/bars}
APP=$ROOT/app
cd "$APP"

[ -f $ROOT/previous.sha ] || { echo "[rollback] FATAL: no previous deployment SHA recorded"; exit 1; }
PREV_SHA=$(cat $ROOT/previous.sha)
echo "$PREV_SHA" | grep -qE '^[0-9a-f]{40}$' || { echo "[rollback] FATAL: previous.sha must be exactly 40 lowercase hex chars, got '$PREV_SHA'"; exit 2; }
CUR=$(cat $ROOT/current.sha 2>/dev/null || echo unknown)
CUR_SNAP=""
[ -f $ROOT/current.snapshot ] && CUR_SNAP=$(cat $ROOT/current.snapshot)
PREV_SNAP=""
[ -f $ROOT/previous.snapshot ] && PREV_SNAP=$(cat $ROOT/previous.snapshot)

docker image inspect "bars-sovereign:$PREV_SHA" >/dev/null 2>&1 || {
  echo "[rollback] FATAL: immutable image bars-sovereign:$PREV_SHA not present"; exit 1; }

if [ "${1:-}" = "--with-data" ]; then
  [ -n "$PREV_SNAP" ] && [ -f "$PREV_SNAP" ] || { echo "[rollback] FATAL: no deployment-linked snapshot for $PREV_SHA"; exit 1; }
  echo "[rollback] stopping service before atomic data replace"
  docker compose -f "$APP/docker-compose.yml" stop 2>/dev/null || true
  TMPD=$(mktemp -d $ROOT/.data-restore-XXXXXX)
  tar -xzf "$PREV_SNAP" -C "$TMPD"
  OLD=$(mktemp -du $ROOT/.data-old-XXXXXX)
  mv $ROOT/data "$OLD"
  mv "$TMPD" $ROOT/data
  echo "[rollback] data replaced atomically from $PREV_SNAP (old data at $OLD)"
else
  echo "[rollback] image-only: post-deploy data/receipts/audit preserved"
fi

echo "[rollback] rolling back from $CUR to $PREV_SHA (immutable image)"
echo "$CUR" > $ROOT/rolled-back-from.sha
[ -n "$CUR_SNAP" ] && echo "$CUR_SNAP" > $ROOT/rolled-back-from.snapshot || true
# relink for REPEATED rollback: previous <- what we abandon, current <- restored
echo "$CUR" > $ROOT/previous.sha
[ -n "$CUR_SNAP" ] && echo "$CUR_SNAP" > $ROOT/previous.snapshot || rm -f $ROOT/previous.snapshot
echo "$PREV_SHA" > $ROOT/current.sha
[ -n "$PREV_SNAP" ] && echo "$PREV_SNAP" > $ROOT/current.snapshot || rm -f $ROOT/current.snapshot

docker tag "bars-sovereign:$PREV_SHA" bars-sovereign:current

BARS_IMAGE="bars-sovereign:$PREV_SHA" docker compose -f "$APP/docker-compose.yml" up -d --force-recreate

i=0
while :; do
  GOT=$(curl -fsS -m 3 http://127.0.0.1:4321/health 2>/dev/null | grep -o '"sha": *"[0-9a-f]*"' | grep -o '[0-9a-f]\{40\}' || true)
  [ "$GOT" = "$PREV_SHA" ] && break
  i=$((i+1)); [ $i -gt 20 ] && { echo "[rollback] FAILED: /health reports '${GOT:-none}', expected $PREV_SHA (image-baked provenance)"; exit 1; }
  sleep 2
done
echo "[rollback] OK: bars-sovereign:$PREV_SHA healthy, /health verifies exact SHA (rolled back from $CUR)"
