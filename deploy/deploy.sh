#!/bin/sh
# BARS sovereign deploy (production). Usage: deploy/deploy.sh <40-hex-git-sha>
# Single source of hardening truth: docker-compose.yml. Reversible via
# deploy/rollback.sh. Data/audit are never touched by deploy or by a default
# rollback.
#
# Every live-surface identifier is parameterized so an isolated integration
# run can never collide with a live deployment: image name, compose project,
# container name, host port, data path, and anchor path all default to the
# production values but can be overridden via BARS_* env vars.
set -eu
SHA="${1:?usage: deploy.sh <40-hex-git-sha>}"
case "$SHA" in
  ????????????????????????????????????????) ;;
  *) echo "[deploy] FATAL: need a full 40-char SHA" >&2; exit 2;;
esac
echo "$SHA" | grep -qE '^[0-9a-f]{40}$' || { echo "[deploy] FATAL: git SHA must be exactly 40 lowercase hex characters, got '$SHA'" >&2; exit 2; }
ROOT=${BARS_ROOT:-/opt/bars}
APP=$ROOT/app
DATA=${BARS_DATA:-$ROOT/data}
IMG=${BARS_IMAGE_NAME:-bars-sovereign}
PORT=${BARS_HOST_PORT:-4321}
PROJECT=${BARS_COMPOSE_PROJECT:-bars}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
cd "$APP"

echo "[deploy] snapshot data -> $ROOT/backups/data-$SHA.tar.gz (deployment-linked)"
mkdir -p "$ROOT/backups"
if ! tar -czf "$ROOT/backups/data-$SHA.tar.gz" -C "$DATA" . 2>/dev/null; then
  # the container writes some state root/0600; a non-root docker host user
  # (CI runners) cannot read it. Snapshot through the previous image instead.
  docker image inspect "$IMG:current" >/dev/null 2>&1 || {
    echo "[deploy] FATAL: data unreadable by host user and no previous image to snapshot through"; exit 1; }
  echo "[deploy] host user cannot read all data files; snapshotting via $IMG:current"
  docker run --rm --user 0 -v "$DATA":/data:ro -v "$ROOT/backups":/backups "$IMG:current"     sh -c "tar -czf /backups/data-$SHA.tar.gz -C /data . && chmod 0666 /backups/data-$SHA.tar.gz"
fi

echo "[deploy] fetch + checkout $SHA"
# refuse to mutate a dirty worktree: check BEFORE checkout, verify AFTER
[ -z "$(git status --porcelain)" ] || { echo "[deploy] FATAL: worktree dirty or untracked files present before checkout - deploy requires a pristine tree" >&2; exit 2; }
git fetch --quiet origin
git checkout --quiet "$SHA"
HEAD_NOW=$(git rev-parse HEAD)
[ "$HEAD_NOW" = "$SHA" ] || { echo "[deploy] FATAL: HEAD $HEAD_NOW != requested $SHA"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "[deploy] FATAL: worktree dirty or untracked files present - deploy requires a pristine checkout of $SHA" >&2; exit 2; }

echo "[deploy] build $IMG:$SHA (exact)"
docker build -q --build-arg BARS_SHA="$SHA" -t "$IMG:$SHA" . >/dev/null

echo "[deploy] preserve current deployment for rollback"
if docker image inspect "$IMG:current" >/dev/null 2>&1; then
  docker tag "$IMG:current" "$IMG:rollback"
fi
[ -f $ROOT/current.sha ] && cp $ROOT/current.sha $ROOT/previous.sha || true
[ -f $ROOT/current.snapshot ] && cp $ROOT/current.snapshot $ROOT/previous.snapshot || true

docker tag "$IMG:$SHA" "$IMG:current"
echo "$SHA" > $ROOT/current.sha
echo "$ROOT/backups/data-$SHA.tar.gz" > $ROOT/current.snapshot

echo "[deploy] compose restart (hardening from docker-compose.yml, project $PROJECT)"
export BARS_GIT_SHA="$SHA"
BARS_IMAGE="$IMG:$SHA" BARS_HOST_PORT="$PORT" docker compose -p "$PROJECT" -f "$APP/docker-compose.yml" up -d --force-recreate

echo "[deploy] wait for health AND exact SHA on 127.0.0.1:$PORT"
i=0
while :; do
  GOT=$(curl -fsS -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -o '"sha": *"[0-9a-f]*"' | grep -o '[0-9a-f]\{40\}' || true)
  [ "$GOT" = "$SHA" ] && break
  i=$((i+1)); [ $i -gt 20 ] && { echo "[deploy] FAILED health/sha (got '${GOT:-none}'); run deploy/rollback.sh"; exit 1; }
  sleep 2
done
echo "[deploy] OK: $IMG:$SHA healthy, /health reports exact SHA"
