#!/bin/sh
# Real Docker-daemon integration test for deploy/rollback image identity.
# Runs only when a daemon is available AND BARS_DOCKER_TEST=1. In the build
# agent there is no daemon; run on the verified VPS pre-cutover instead.
set -eu
if [ "${BARS_DOCKER_TEST:-}" != "1" ] || ! docker info >/dev/null 2>&1; then
  echo "SKIP: no Docker daemon or BARS_DOCKER_TEST!=1 (run on the VPS pre-cutover)"
  exit 0
fi
ROOT=$(mktemp -d /tmp/bars-docker-test-XXXXXX)
trap 'rm -rf "$ROOT"' EXIT
export BARS_ROOT="$ROOT/root"
mkdir -p "$BARS_ROOT/app" "$BARS_ROOT/data" "$BARS_ROOT/backups"
cp -r . "$BARS_ROOT/app/src" 2>/dev/null || true
cd "$BARS_ROOT/app/src"
git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm A
SHA_A=$(git rev-parse HEAD)
echo change >> CHANGELOG.md && git add -A && git -c user.name=t -c user.email=t@t commit -qm B
SHA_B=$(git rev-parse HEAD)
mv "$BARS_ROOT/app/src"/* "$BARS_ROOT/app/" 2>/dev/null || true; mv "$BARS_ROOT/app/src"/.git "$BARS_ROOT/app/"
cd "$BARS_ROOT/app"
sh deploy/deploy.sh "$SHA_A"
sh deploy/deploy.sh "$SHA_B"
docker image inspect "bars-sovereign:$SHA_A" >/dev/null   # immutable images exist
docker image inspect "bars-sovereign:$SHA_B" >/dev/null
sh deploy/rollback.sh
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_A" ]
docker image inspect "bars-sovereign:$SHA_A" >/dev/null
echo "DOCKER INTEGRATION: deploy/rollback image identity OK ($SHA_A <-> $SHA_B)"
