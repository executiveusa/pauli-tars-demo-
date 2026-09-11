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
  for i in $(docker images -q "$IMG" | sort -u); do docker image rm -f "$i" >/dev/null 2>&1 || true; done
  rm -rf "$ROOT"
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

echo "deploy A ($SHA_A)"
sh deploy/deploy.sh "$SHA_A" >/dev/null
[ "$(curl -fsS -m 3 http://127.0.0.1:$TEST_PORT/health | grep -o '[0-9a-f]\{40\}')" = "$SHA_A" ]
echo "deploy B ($SHA_B)"
sh deploy/deploy.sh "$SHA_B" >/dev/null
[ "$(curl -fsS -m 3 http://127.0.0.1:$TEST_PORT/health | grep -o '[0-9a-f]\{40\}')" = "$SHA_B" ]
docker image inspect "$IMG:$SHA_A" >/dev/null   # immutable images both exist
docker image inspect "$IMG:$SHA_B" >/dev/null

echo "rollback -> A"
sh deploy/rollback.sh >/dev/null
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_A" ]
[ "$(curl -fsS -m 3 http://127.0.0.1:$TEST_PORT/health | grep -o '[0-9a-f]\{40\}')" = "$SHA_A" ]
echo "rollback -> B"
sh deploy/rollback.sh >/dev/null
[ "$(cat $BARS_ROOT/current.sha)" = "$SHA_B" ]
[ "$(curl -fsS -m 3 http://127.0.0.1:$TEST_PORT/health | grep -o '[0-9a-f]\{40\}')" = "$SHA_B" ]

echo "DOCKER INTEGRATION: deploy/rollback image identity OK ($SHA_A <-> $SHA_B, port $TEST_PORT, project $PROJECT)"
