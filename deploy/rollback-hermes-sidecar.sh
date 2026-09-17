#!/usr/bin/env bash
set -euo pipefail

ROOT=${BARS_ROOT:-/opt/bars}
ENV_FILE=${HERMES_ENV_FILE:-$ROOT/hermes.env}
DATA=${HERMES_DATA:-$ROOT/hermes}
COMPOSE=${HERMES_COMPOSE_FILE:-$ROOT/app/deploy/hermes-sidecar.compose.yml}
PROJECT=${HERMES_COMPOSE_PROJECT:-bars-hermes}
PORT=${HERMES_HOST_PORT:-8642}
PREV_FILE="$ROOT/hermes.previous-image"
CUR_FILE="$ROOT/hermes.current-image"

[[ -f "$PREV_FILE" ]] || { echo "[hermes-rollback] no previous image recorded" >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "[hermes-rollback] missing $ENV_FILE" >&2; exit 2; }
PREV=$(cat "$PREV_FILE")
[[ "$PREV" == *@sha256:* ]] || { echo "[hermes-rollback] previous image is not digest-pinned" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
[[ -n "${API_SERVER_KEY:-}" ]] || { echo "[hermes-rollback] API_SERVER_KEY missing" >&2; exit 2; }

CUR=$(cat "$CUR_FILE" 2>/dev/null || true)
export HERMES_IMAGE="$PREV"

echo "[hermes-rollback] restoring $PREV"
HERMES_ENV_FILE="$ENV_FILE" HERMES_DATA="$DATA" HERMES_HOST_PORT="$PORT" \
  docker compose -p "$PROJECT" -f "$COMPOSE" up -d --force-recreate

for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 \
      -H "Authorization: Bearer $API_SERVER_KEY" \
      "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    printf '%s\n' "$PREV" > "$CUR_FILE"
    [[ -n "$CUR" ]] && printf '%s\n' "$CUR" > "$PREV_FILE"
    echo "[hermes-rollback] OK: previous Hermes runtime is reachable"
    exit 0
  fi
  sleep 2
done

echo "[hermes-rollback] FAILED: restored image did not pass authenticated probe" >&2
exit 1
