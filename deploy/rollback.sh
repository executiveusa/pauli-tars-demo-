#!/bin/sh
# BARS rollback. Runs the IMMUTABLE image of the previous deployment
# ($IMG:$PREV_SHA) and verifies /health reports that exact SHA from
# image-baked provenance. Bookkeeping (current/previous + snapshot links +
# rolled-back-from) is rewritten ONLY after health succeeds; on failure the
# prior bookkeeping is left untouched and the current tag is restored.
# Default: image-only - post-deploy data/receipts/audit preserved.
# --with-data: stop the service, then ATOMICALLY replace data with the
# snapshot linked to the restored deployment (never an overlay extract).
#
# Same BARS_* parameterization as deploy.sh: an isolated integration run uses
# its own image name, project, container, port, data and anchor paths and can
# never touch a live deployment's resources.
set -eu
ROOT=${BARS_ROOT:-/opt/bars}
APP=$ROOT/app
DATA=${BARS_DATA:-$ROOT/data}
IMG=${BARS_IMAGE_NAME:-bars-sovereign}
PORT=${BARS_HOST_PORT:-4321}
PROJECT=${BARS_COMPOSE_PROJECT:-bars}
cd "$APP"

[ -f $ROOT/previous.sha ] || { echo "[rollback] FATAL: no previous deployment SHA recorded"; exit 1; }
PREV_SHA=$(cat $ROOT/previous.sha)
echo "$PREV_SHA" | grep -qE '^[0-9a-f]{40}$' || { echo "[rollback] FATAL: previous.sha must be exactly 40 lowercase hex chars, got '$PREV_SHA'"; exit 2; }
CUR=$(cat $ROOT/current.sha 2>/dev/null || echo unknown)
CUR_SNAP=""
[ -f $ROOT/current.snapshot ] && CUR_SNAP=$(cat $ROOT/current.snapshot)
PREV_SNAP=""
[ -f $ROOT/previous.snapshot ] && PREV_SNAP=$(cat $ROOT/previous.snapshot)

docker image inspect "$IMG:$PREV_SHA" >/dev/null 2>&1 || {
  echo "[rollback] FATAL: immutable image $IMG:$PREV_SHA not present"; exit 1; }

if [ "${1:-}" = "--with-data" ]; then
  [ -n "$PREV_SNAP" ] && [ -f "$PREV_SNAP" ] || { echo "[rollback] FATAL: no deployment-linked snapshot for $PREV_SHA"; exit 1; }
  echo "[rollback] stopping service before atomic data replace"
  docker compose -p "$PROJECT" -f "$APP/docker-compose.yml" stop 2>/dev/null || true
  if [ "$(id -u)" = "0" ]; then
    TMPD=$(mktemp -d $ROOT/.data-restore-XXXXXX)
    tar -xzf "$PREV_SNAP" -C "$TMPD"
    OLD=$(mktemp -du $ROOT/.data-old-XXXXXX)
    mv "$DATA" "$OLD"
    mv "$TMPD" "$DATA"
    echo "[rollback] data replaced atomically from $PREV_SNAP (old data at $OLD)"
  else
    # non-root docker host (CI runners): the container-written state is
    # uid-10001/0600 and the restored files must keep that ownership, so the
    # extract+swap runs as root inside the immutable previous image.
    [ "$DATA" = "$ROOT/data" ] || {
      echo "[rollback] FATAL: non-root host supports only BARS_DATA=\$BARS_ROOT/data" >&2; exit 2; }
    SNAPIN="/baroot/${PREV_SNAP#$ROOT/}"
    docker run --rm --user 0 -e SNAP="$SNAPIN" -v "$ROOT":/baroot "$IMG:$PREV_SHA" sh -c '
      set -e
      T=$(mktemp -d /baroot/.data-restore-XXXXXX)
      tar -xzf "$SNAP" -C "$T"
      O=$(mktemp -du /baroot/.data-old-XXXXXX)
      mv /baroot/data "$O"
      mv "$T" /baroot/data
      echo "[rollback] data replaced atomically from $SNAP (old data at $O, via docker)"
    '
  fi
else
  echo "[rollback] image-only: post-deploy data/receipts/audit preserved"
fi

echo "[rollback] rolling back from $CUR to $PREV_SHA (immutable image, project $PROJECT)"
BARS_IMAGE="$IMG:$PREV_SHA" BARS_HOST_PORT="$PORT" docker compose -p "$PROJECT" -f "$APP/docker-compose.yml" up -d --force-recreate

i=0
HEALTHY=""
while :; do
  GOT=$(curl -fsS -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -o '"sha": *"[0-9a-f]*"' | grep -o '[0-9a-f]\{40\}' || true)
  if [ "$GOT" = "$PREV_SHA" ]; then HEALTHY=1; break; fi
  i=$((i+1)); [ $i -gt 20 ] && break
  sleep 2
done

if [ -z "$HEALTHY" ]; then
  echo "[rollback] FAILED: /health reports '${GOT:-none}', expected $PREV_SHA" >&2
  # bookkeeping untouched; restore the current tag to the abandoned image
  if echo "$CUR" | grep -qE '^[0-9a-f]{40}$'; then
    docker tag "$IMG:$CUR" "$IMG:current" 2>/dev/null || true
  fi
  echo "[rollback] prior bookkeeping restored; service left on attempted image - investigate before retry" >&2
  exit 1
fi

# health verified: NOW relink atomically (previous <- abandoned, current <- restored)
docker tag "$IMG:$PREV_SHA" "$IMG:current"
echo "$CUR" > $ROOT/rolled-back-from.sha
[ -n "$CUR_SNAP" ] && echo "$CUR_SNAP" > $ROOT/rolled-back-from.snapshot || true
echo "$CUR" > $ROOT/previous.sha
[ -n "$CUR_SNAP" ] && echo "$CUR_SNAP" > $ROOT/previous.snapshot || rm -f $ROOT/previous.snapshot
echo "$PREV_SHA" > $ROOT/current.sha
[ -n "$PREV_SNAP" ] && echo "$PREV_SNAP" > $ROOT/current.snapshot || rm -f $ROOT/current.snapshot
echo "[rollback] OK: $IMG:$PREV_SHA healthy, /health verifies exact SHA (rolled back from $CUR)"
