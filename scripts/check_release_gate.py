#!/usr/bin/env python3
"""Release-gate wiring check: the Open Code Review flow must be installed and
point at the central reusable workflow; the builder never self-approves."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fail = []

wf = (ROOT / ".github" / "workflows" / "vibe-code-review.yml")
if not wf.exists():
    fail.append("missing .github/workflows/vibe-code-review.yml")
elif "executiveusa/open-code-review/.github/workflows/vibe-code-review.yml@864933213372cc488b3f2f2b1deaab84ea91b855" not in wf.read_text():
    fail.append("workflow does not call the central reusable OCR workflow")

agents = (ROOT / "AGENTS.md").read_text()
if "<!-- VIBE_REVIEW:START -->" not in agents or "<!-- VIBE_REVIEW:END -->" not in agents:
    fail.append("AGENTS.md missing managed VIBE_REVIEW block")

for d in (".agents", ".claude", ".codex", ".cursor"):
    if not (ROOT / d / "skills" / "vibe-project-review" / "SKILL.md").exists():
        fail.append(f"missing skill in {d}")

if (ROOT / ".opencodereview" / "rule.json").exists():
    fail.append("candidate .opencodereview/rule.json present: the candidate must "
                "not control its own judge - policy comes from the centrally pinned action")

doc = ROOT / "docs" / "SOFTWARE_FACTORY_GATE.md"
if not doc.exists() or "centrally pinned policy" not in doc.read_text():
    fail.append("gate doc must name the centrally pinned policy source")


if fail:
    print("RELEASE GATE WIRING: FAIL"); [print(" -", f) for f in fail]; sys.exit(1)
print("RELEASE GATE WIRING: PASS")
