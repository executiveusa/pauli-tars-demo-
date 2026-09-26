#!/usr/bin/env bash
# Install or update the video-authoring skills for the BARS video engine.
#
#   media/hyperframes/install-skills.sh [WORKSPACE_DIR]      (default /srv/video)
#
# 1. The official HyperFrames core skills (router + domain skills), installed and linked into every
#    compatible agent on this box for the current user: `npx hyperframes skills update`.
# 2. Nate Herk's HyperFrames student kit (github.com/nateherkai/hyperframes-student-kit, MIT + kit
#    permission), pinned to a reviewed commit, as the agents' video workspace. Its 15 skills
#    (edit-video, short-form-edit, motion-showreel, style-library, ...) call the kit's own scripts
#    and style library, so the kit is installed whole, not as loose skill files.
#    Excluded: the AI Automation Society brand assets and AIS projects (not licensed for reuse),
#    the showcase videos, and the 287 MB of sample projects.
#
# Point the render service at the kit's projects:  HYPERFRAMES_WORKSPACE_ROOT=$WORKSPACE_DIR/kit/video-projects
# Re-run any time to update: the core skills refresh, and the kit moves to KIT_REF.
set -euo pipefail

WORKSPACE_DIR="${1:-/srv/video}"
KIT_REPO="https://github.com/nateherkai/hyperframes-student-kit.git"
KIT_REF="ec112ff27abb68ed2086640c18668af8ae1c1fc4"   # reviewed 2026-09-26; bump deliberately
KIT_DIR="$WORKSPACE_DIR/kit"
export HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)" >&2; exit 1; }; }
need git "apt-get install -y git"
need node "Node.js 22+"
need npx "Node.js 22+"
need ffmpeg "apt-get install -y ffmpeg"
need ffprobe "apt-get install -y ffmpeg (ffprobe ships with it)"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' \
  || { echo "Node.js 22+ required (found $(node -v))" >&2; exit 1; }

echo "== 1/3 official HyperFrames core skills"
npx --yes hyperframes@0.8.78 skills update
npx --yes hyperframes@0.8.78 skills check

echo "== 2/3 student kit @ ${KIT_REF:0:12} -> $KIT_DIR"
mkdir -p "$WORKSPACE_DIR"
if [ ! -d "$KIT_DIR/.git" ]; then
  git clone --quiet --no-checkout --filter=blob:none "$KIT_REPO" "$KIT_DIR"
fi
git -C "$KIT_DIR" fetch --quiet origin "$KIT_REF"
# Everything except brand assets, showcase media and the bundled sample projects.
git -C "$KIT_DIR" sparse-checkout set --no-cone '/*' '!/assets/' '!/DESIGN.ais-example.md' \
  '!/examples/showcase/' '!/video-projects/*' '/video-projects/.gitkeep'
git -C "$KIT_DIR" checkout --quiet --force "$KIT_REF"
test "$(git -C "$KIT_DIR" rev-parse HEAD)" = "$KIT_REF" || { echo "kit is not at $KIT_REF" >&2; exit 1; }
mkdir -p "$KIT_DIR/video-projects"
for excluded in assets DESIGN.ais-example.md examples/showcase; do
  test ! -e "$KIT_DIR/$excluded" || { echo "brand/showcase material still present: $excluded" >&2; exit 1; }
done

echo "== 3/3 kit dependencies and self-test"
(cd "$KIT_DIR" && npm ci --no-audit --no-fund && npm test)

skills=$(ls "$KIT_DIR/.claude/skills" | tr '\n' ' ')
echo
echo "Installed. Kit skills: $skills"
echo "Agents: open $KIT_DIR in Claude Code or Codex and use /hyperframes, /edit-video, /short-form-edit, ..."
echo "Render service: HYPERFRAMES_WORKSPACE_ROOT=$KIT_DIR/video-projects"
