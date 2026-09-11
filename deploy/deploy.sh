#!/bin/sh
# BARS sovereign deploy (production). Usage: deploy/deploy.sh <40-hex-git-sha>
# Single source of hardening truth: docker-compose.yml. Reversible via
# deploy/rollback.sh. Data/audit are never touched by deploy or by a default
# rollback.
set -eu
SHA="${1:?usage: deploy.sh <40-hex-git-sha>}"
case "$SHA" in
  ????????????????????????????????????????) ;;
  *) echo "[deploy] FATAL: need a full 40-char SHA" >&2; exit 2;;
esac
echo "$SHA" | grep -qE '^[0-9a-f]{40}$' || { echo "[deploy] FATAL: git SHA must be exactly 40 lowercase hex characters, got '$SHA'" >&2; exit 2; }
ROOT=${BARS_ROOT:-/opt/bars}
APP=$ROOT/app
DATA=$ROOT/data
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
cd "$APP"

echo "[deploy] snapshot data -> $ROOT/backups/data-$SHA.tar.gz (deployment-linked)"
mkdir -p "$ROOT/backups"
tar -czf "$ROOT/backups/data-$SHA.tar.gz" -C "$DATA" .

echo "[deploy] fetch + checkout $SHA"
git fetch --quiet origin
git checkout --quiet "$SHA"
HEAD_NOW=$(git rev-parse HEAD)
[ "$HEAD_NOW" = "$SHA" ] || { echo "[deploy] FATAL: HEAD $HEAD_NOW != requested $SHA"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "[deploy] FATAL: worktree dirty or untracked files present - deploy requires a pristine checkout of $SHA" >&2; exit 2; }

echo "[deploy] build bars-sovereign:$SHA (exact)"
docker build -q --build-arg BARS_SHA="$SHA" -t "bars-sovereign:$SHA" . >/dev/null

echo "[deploy] preserve current deployment for rollback"
if docker image inspect bars-sovereign:current >/dev/null 2>&1; then
  docker tag bars-sovereign:current bars-sovereign:rollback
fi
[ -f $ROOT/current.sha ] && cp $ROOT/current.sha $ROOT/previous.sha || true
[ -f $ROOT/current.snapshot ] && cp $ROOT/current.snapshot $ROOT/previous.snapshot || true

docker tag "bars-sovereign:$SHA" bars-sovereign:current
echo "$SHA" > $ROOT/current.sha
echo "$ROOT/backups/data-$SHA.tar.gz" > $ROOT/current.snapshot

echo "[deploy] compose restart (hardening from docker-compose.yml)"
export BARS_GIT_SHA="$SHA"
BARS_IMAGE="bars-sovereign:$SHA" docker compose -f "$APP/docker-compose.yml" up -d --force-recreate

echo "[deploy] wait for health AND exact SHA"
i=0
while :; do
  GOT=$(curl -fsS -m 3 http://127.0.0.1:4321/health 2>/dev/null | grep -o '"sha": *"[0-9a-f]*"' | grep -o '[0-9a-f]\{40\}' || true)
  [ "$GOT" = "$SHA" ] && break
  i=$((i+1)); [ $i -gt 20 ] && { echo "[deploy] FAILED health/sha (got '${GOT:-none}'); run deploy/rollback.sh"; exit 1; }
  sleep 2
done
echo "[deploy] OK: bars-sovereign:$SHA healthy, /health reports exact SHA"
