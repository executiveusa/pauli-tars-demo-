#!/usr/bin/env bash
set -euo pipefail

# Build a BARS-capable Hermes working tree without copying credentials or runtime state.
# Usage:
#   ./scripts/build-bars-hermes-runtime.sh /path/to/pauli-hermes /path/to/hermes-upstream [/path/to/output]
#
# The script intentionally operates on local working trees so a software factory can
# review diffs, run upstream tests, and only then publish/deploy the runtime.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE=${1:-}
UPSTREAM=${2:-}
OUTPUT=${3:-./.bars-runtime}

if [[ -z "$SOURCE" || -z "$UPSTREAM" ]]; then
  echo "usage: $0 <pauli-hermes-source> <clean-hermes-upstream> [output]" >&2
  exit 64
fi

for dir in "$SOURCE" "$UPSTREAM"; do
  [[ -d "$dir" ]] || { echo "missing directory: $dir" >&2; exit 66; }
done

[[ -f "$UPSTREAM/run_agent.py" ]] || {
  echo "upstream does not look like NousResearch/hermes-agent: $UPSTREAM" >&2
  exit 65
}

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"
cp -a "$UPSTREAM/." "$OUTPUT/"

required=(
  skills/adhd-elegant-simplicity-v2
  skills/agent-maxx
  skills/gauntlet-loop
  skills/hardened-longrun-subagent-harness
  skills/studio/vibe-client-factory
  skills/studio/cinematic-master-editor
  skills/studio/cinematic-2-5d-scenes
  skills/studio/interactive-artifact
  skills/studio/website-design
)

optional=(
  skills/21st-dev-mcp
  skills/agent-reach
  skills/api-opportunity-orchestrator
  skills/art-of-reduction
  skills/autonomous-ai-agents
  skills/browser-hosting-deployer
  skills/local-footage-studio
  skills/scroll-media-operator
  skills/social-drop-factory
  skills/riverside-flow
  skills/youtube-channel-operator
  skills/workflows/sovereign-vps-operator
  skills/studio/awwwards-design-intelligence
  skills/studio/campaign-factory
)

copy_skill() {
  local rel=$1
  local mode=$2
  if [[ ! -d "$SOURCE/$rel" ]]; then
    if [[ "$mode" == required ]]; then
      echo "required skill missing from source: $rel" >&2
      exit 67
    fi
    echo "optional skill absent, skipping: $rel"
    return 0
  fi
  mkdir -p "$OUTPUT/$(dirname "$rel")"
  rm -rf "$OUTPUT/$rel"
  cp -a "$SOURCE/$rel" "$OUTPUT/$rel"
  echo "installed: $rel"
}

for rel in "${required[@]}"; do copy_skill "$rel" required; done
for rel in "${optional[@]}"; do copy_skill "$rel" optional; done

# Install the BARS-native lean router and machine-readable live registry from this repo.
# These contracts are distinct from external skill bodies: a manifest-contract is routable,
# but must not be reported as a physically resolved third-party skill package.
[[ -f "$REPO_ROOT/.agents/skills/bars-skill-router/SKILL.md" ]] || {
  echo "missing BARS router skill" >&2
  exit 68
}
[[ -f "$REPO_ROOT/bars/skills/live-registry.json" ]] || {
  echo "missing BARS live skill registry" >&2
  exit 69
}
mkdir -p "$OUTPUT/skills/bars-skill-router" "$OUTPUT/bars/skills"
cp -a "$REPO_ROOT/.agents/skills/bars-skill-router/." "$OUTPUT/skills/bars-skill-router/"
cp -a "$REPO_ROOT/bars/skills/live-registry.json" "$OUTPUT/bars/skills/live-registry.json"
python -m json.tool "$OUTPUT/bars/skills/live-registry.json" >/dev/null

echo "installed: skills/bars-skill-router"
echo "installed: bars/skills/live-registry.json"

mkdir -p "$OUTPUT/bars"
cat > "$OUTPUT/bars/PROFILE.md" <<'PROFILE'
# BARS Hermes profile

BARS is the artist-product and media operator profile.

- use Hermes tools/skills rather than simulating actions
- route work through `bars/skills/live-registry.json` and `skills/bars-skill-router`
- prefer one canonical entry point per overlapping skill family
- keep archived/template skill catalogs out of live context unless explicitly requested
- preserve the PARÉ spine as one coherent design doctrine
- prefer scoped APIs/MCP/Composio to browser automation
- preserve source/asset provenance and owner control
- use separate builder and critic for release-bound creative work
- never claim an external action succeeded without evidence
- never claim a manifest-contract skill body is physically installed unless its source path resolves
- require approval for publishing, spending, destructive changes or account mutations
- keep providers replaceable behind adapters
PROFILE

cat > "$OUTPUT/bars/INTEGRATIONS.example.yaml" <<'YAML'
# Example only. Do not commit real secrets.
mcp_servers:
  composio:
    url: "https://connect.composio.dev/mcp"
    # Configure auth in the Hermes runtime according to the current Composio flow.

providers:
  opensuno:
    url: "${OPENSUNO_URL}"
  visual_provider:
    url: "${VISUAL_PROVIDER_URL}"
YAML

# Secret/auth state must never be carried from the customized source tree.
find "$OUTPUT" -type f \( \
  -name '.env' -o \
  -name 'auth.json' -o \
  -name '*credential*' -o \
  -name '*token*' \
\) -print > "$OUTPUT/bars/secret-scan-candidates.txt"

if [[ -s "$OUTPUT/bars/secret-scan-candidates.txt" ]]; then
  echo "review required: possible secret-bearing files exist in the clean upstream/output tree" >&2
  cat "$OUTPUT/bars/secret-scan-candidates.txt" >&2
fi

cat > "$OUTPUT/bars/BUILD_RECEIPT.txt" <<EOF
BARS overlay built: $(date -u +%Y-%m-%dT%H:%M:%SZ)
source=$SOURCE
upstream=$UPSTREAM
output=$OUTPUT
required_skills=${#required[@]}
optional_skills=${#optional[@]}
bars_router_skill=installed
bars_live_registry=installed
status=BUILT_NOT_VERIFIED
next=run upstream tests, start Hermes API server, then execute BARS integration smoke tests
EOF

echo
cat "$OUTPUT/bars/BUILD_RECEIPT.txt"
