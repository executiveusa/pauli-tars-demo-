#!/bin/sh
# Real Docker-daemon integration test for deploy/rollback image identity.
# FULLY ISOLATED: its own image name, compose project, container name, host
# port, data path, and anchor path. It never touches a live BARS container,
# port, volume, or data, and it proves that isolation BEFORE creating
# anything. Skips unless BARS_DOCKER_TEST=1 AND a daemon is reachable.
set -eu
if [ "${BARS_DOCKER_TEST:-}" != "1" ] || ! docker info >/dev/null 2>&1; then
  echo "SKIP: no Docker daemon or BARS_DOCKER_TEST!=1 (run on an isolated surface)"
  exit 0
fi

TEST_PORT=${BARS_TEST_PORT:-18099}
IMG=bars-sovereign-integration-test
PROJECT=barsintegrationtest
CONTAINER=bars-integration-test

# --- prove isolation BEFORE creating anything -------------------------------
if curl -fsS -m 2 "http://127.0.0.1:$TEST_PORT/health" >/dev/null 2>&1; then
  echo "FATAL: 127.0.0.1:$TEST_PORT already serves HTTP - isolation cannot be proven" >&2; exit 1
fi
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "FATAL: container $CONTAINER already exists - isolation cannot be proven" >&2; exit 1
fi
if docker compose ls 2>/dev/null | grep -q "$PROJECT"; then
  echo "FATAL: compose project $PROJECT already exists - isolation cannot be proven" >&2; exit 1
fi
echo "ISOLATION PROVEN: port $TEST_PORT free, no container $CONTAINER, no project $PROJECT"

ROOT=$(mktemp -d /tmp/bars-docker-test-XXXXXX)
cleanup() {
  rc=$1
  if [ "$rc" != "0" ]; then
    echo "---- failure diagnostics: container logs ----" >&2
    docker logs "$CONTAINER" 2>&1 | tail -40 >&2 || true
    docker ps -a --filter "name=$CONTAINER" >&2 || true
  fi
  docker compose -p "$PROJECT" -f "$ROOT/root/app/docker-compose.yml" down -v >/dev/null 2>&1 || true
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  # container-written state is uid-10001/0600: a non-root host user cannot
  # remove it directly - chmod through a throwaway container first
  docker run --rm -v "$ROOT":/x python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea \
    sh -c "chmod -R 0777 /x" >/dev/null 2>&1 || true
  rm -rf "$ROOT" 2>/dev/null || true
}
trap 'cleanup $?' EXIT

export BARS_ROOT="$ROOT/root"
export BARS_DATA="$BARS_ROOT/data"
export BARS_ANCHOR="$BARS_ROOT/anchor"
export BARS_IMAGE_NAME="$IMG"
export BARS_COMPOSE_PROJECT="$PROJECT"
export BARS_CONTAINER_NAME="$CONTAINER"
export BARS_HOST_PORT="$TEST_PORT"
export BARS_ENV_FILE="$ROOT/test.env"
mkdir -p "$BARS_DATA" "$BARS_ROOT/backups" "$BARS_ANCHOR"
# container runs as uid 10001 and must write /data and /anchor. The docker
# HOST user varies (root on the VPS, uid 1001 on CI runners), so make the
# throwaway tmp dirs world-writable instead of chowning.
chmod 0777 "$BARS_DATA" "$BARS_ANCHOR"
# throwaway test-only token (the server refuses to boot without one); no real
# secrets - health/identity need no provider keys
echo "BARS_OPERATOR_TOKEN=integration-test-token" > "$ROOT/test.env"

# --- offline-safe synthetic repo with a real (local-path) origin -------------
# trees copied across hosts may carry foreign uids; git refuses them otherwise
git config --global --add safe.directory "$ROOT/work" 2>/dev/null || true
git config --global --add safe.directory "$BARS_ROOT/app" 2>/dev/null || true
git init -q --bare "$ROOT/origin.git"
git clone -q "$ROOT/origin.git" "$ROOT/work"
tar --exclude=./.git -cf - . | tar -xf - -C "$ROOT/work"
cd "$ROOT/work"
git add -A && git -c user.name=t -c user.email=t@t commit -qm A
SHA_A=$(git rev-parse HEAD)
echo change >> CHANGELOG.md && git add -A && git -c user.name=t -c user.email=t@t commit -qm B
SHA_B=$(git rev-parse HEAD)
git push -q origin HEAD:main
git -C "$ROOT/origin.git" symbolic-ref HEAD refs/heads/main   # clone checks out main
git clone -q "$ROOT/origin.git" "$BARS_ROOT/app"
cd "$BARS_ROOT/app"

health_sha() { curl -fsS -m 3 "http://127.0.0.1:$TEST_PORT/health" | grep -o '[0-9a-f]\{40\}'; }

echo "deploy A ($SHA_A)"
sh deploy/deploy.sh "$SHA_A"
[ "$(health_sha)" = "$SHA_A" ]
echo "deploy B ($SHA_B)"
sh deploy/deploy.sh "$SHA_B"
[ "$(health_sha)" = "$SHA_B" ]
docker image inspect "$IMG:$SHA_A" >/dev/null   # immutable images both exist
docker image inspect "$IMG:$SHA_B" >/dev/null
if [ "$(id -u)" != "0" ]; then
  echo "non-root host: snapshot fallback must have been used"
  sh deploy/deploy.sh "$SHA_B" 2>&1 | grep -q "snapshotting via" && echo "snapshot fallback: confirmed" || {
    echo "FATAL: snapshot fallback did not trigger on non-root host" >&2; exit 1; }
fi

echo "rollback -> A"
sh deploy/rollback.sh
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_A" ]
[ "$(health_sha)" = "$SHA_A" ]
echo "rollback -> B"
sh deploy/rollback.sh
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_B" ]
[ "$(health_sha)" = "$SHA_B" ]

# --- failed-health rollback: bookkeeping and tag untouched ------------------
echo "failed-health rollback: broken env must leave bookkeeping untouched"
echo "# broken" > "$ROOT/test.env"
set +e
sh deploy/rollback.sh
RC=$?
set -e
[ "$RC" != "0" ]
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_B" ]
[ "$(cat $BARS_ROOT/previous.sha)" = "$SHA_A" ]
# rolled-back-from.sha must be UNCHANGED (still A from the rollback -> B above)
[ "$(cat $BARS_ROOT/rolled-back-from.sha)" = "$SHA_A" ]
echo "BARS_OPERATOR_TOKEN=integration-test-token" > "$ROOT/test.env"
# the failed rollback leaves the service crash-looping BY DESIGN; restore the
# env and recreate so the service is healthy B again before the next phase
BARS_IMAGE="$IMG:current" BARS_HOST_PORT="$TEST_PORT" docker compose -p "$PROJECT" -f "$ROOT/root/app/docker-compose.yml" up -d --force-recreate >/dev/null 2>&1
i=0; while [ "$(health_sha)" != "$SHA_B" ]; do i=$((i+1)); [ $i -gt 20 ] && { echo "FATAL: service did not recover after env restore" >&2; exit 1; }; sleep 2; done
echo "failed-health behavior OK (rc=$RC, bookkeeping untouched; service recovered to healthy B)"

# --- --with-data rollback: atomic data restore linked to the deployment -----
echo "with-data: marker v2 written post-deploy-B, rollback --with-data -> A restores A snapshot (empty)"
docker exec --user 0 "$CONTAINER" sh -c "echo v2 > /data/marker.txt"
sh deploy/rollback.sh --with-data
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_A" ]
[ "$(health_sha)" = "$SHA_A" ]
[ "$(cat $BARS_ROOT/rolled-back-from.sha)" = "$SHA_B" ]
if docker exec --user 0 "$CONTAINER" sh -c "test -f /data/marker.txt" 2>/dev/null; then
  echo "FATAL: marker survived --with-data rollback to A (data not restored)" >&2; exit 1
fi
echo "with-data -> A OK (marker gone, bookkeeping swapped)"
sh deploy/rollback.sh --with-data
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_B" ]
# B's deployment-linked snapshot predates the marker too: data is empty again
if docker exec --user 0 "$CONTAINER" sh -c "test -f /data/marker.txt" 2>/dev/null; then
  echo "FATAL: marker present after --with-data rollback to B (wrong snapshot)" >&2; exit 1
fi
echo "with-data -> B OK (restored exactly the B-linked snapshot)"

echo "DOCKER INTEGRATION: deploy/rollback image identity OK ($SHA_A <-> $SHA_B, port $TEST_PORT, project $PROJECT)"
