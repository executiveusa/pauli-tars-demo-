#!/usr/bin/env bash
set -euo pipefail

ROOT=${BARS_ROOT:-/opt/bars}
ENV_FILE=${HERMES_ENV_FILE:-$ROOT/hermes.env}
DATA=${HERMES_DATA:-$ROOT/hermes}
COMPOSE=${HERMES_COMPOSE_FILE:-$ROOT/app/deploy/hermes-sidecar.compose.yml}
PROJECT=${HERMES_COMPOSE_PROJECT:-bars-hermes}
PORT=${HERMES_HOST_PORT:-8642}

[[ -f "$ENV_FILE" ]] || { echo "[hermes] missing $ENV_FILE" >&2; exit 2; }
chmod 600 "$ENV_FILE" 2>/dev/null || true
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

[[ -n "${HERMES_IMAGE:-}" ]] || { echo "[hermes] HERMES_IMAGE is required" >&2; exit 2; }
[[ "$HERMES_IMAGE" == *@sha256:* ]] || {
  echo "[hermes] production requires an immutable digest-pinned HERMES_IMAGE" >&2
  exit 2
}
[[ -n "${API_SERVER_KEY:-}" && ${#API_SERVER_KEY} -ge 32 ]] || {
  echo "[hermes] API_SERVER_KEY must be at least 32 characters" >&2
  exit 2
}

mkdir -p "$DATA"
chmod 700 "$DATA" 2>/dev/null || true

PREV_FILE="$ROOT/hermes.previous-image"
CUR_FILE="$ROOT/hermes.current-image"
if [[ -f "$CUR_FILE" ]]; then cp "$CUR_FILE" "$PREV_FILE"; fi

echo "[hermes] pulling immutable image"
docker pull "$HERMES_IMAGE" >/dev/null

echo "[hermes] starting sidecar on loopback :$PORT"
HERMES_ENV_FILE="$ENV_FILE" HERMES_DATA="$DATA" HERMES_HOST_PORT="$PORT" \
  docker compose -p "$PROJECT" -f "$COMPOSE" up -d --force-recreate

echo "[hermes] authenticated API probe"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 \
      -H "Authorization: Bearer $API_SERVER_KEY" \
      "http://127.0.0.1:$PORT/v1/models" >/tmp/bars-hermes-models.json 2>/dev/null; then
    printf '%s\n' "$HERMES_IMAGE" > "$CUR_FILE"
    chmod 600 "$CUR_FILE" "$PREV_FILE" 2>/dev/null || true
    echo "[hermes] READY: authenticated /v1/models succeeded"
    exit 0
  fi
  sleep 2
done

echo "[hermes] FAILED: runtime did not pass authenticated probe" >&2
exit 1
