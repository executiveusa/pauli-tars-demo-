from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

skill = ROOT / ".agents/skills/composio/SKILL.md"
source = ROOT / ".agents/skills/composio/SOURCE.json"
api = (ROOT / "api/composio.js").read_text()
caps = (ROOT / "lib/bars-capabilities.js").read_text()
build = (ROOT / "scripts/build-bars-hermes-runtime.sh").read_text()
overlay = json.loads((ROOT / "bars/hermes-overlay.json").read_text())

assert skill.exists(), "official Composio skill missing"
assert source.exists(), "Composio skill provenance missing"
meta = json.loads(source.read_text())
assert meta["source"] == "ComposioHQ/composio"
assert meta["resolved_commit"] == "b27c24d00d952570f31c44f2f319008761f28c35"

assert "process.env.BARS_COMPOSIO_TOKEN || process.env.COMPOSIO_API_KEY" in api
assert "cfg.id || (cfg.auth_config && cfg.auth_config.id)" in api
assert "https://backend.composio.dev/api/v3.1" in api
assert "BARS_COMPOSIO_TOKEN" in caps
assert 'cp -a "$REPO_ROOT/.agents/skills/composio/." "$OUTPUT/skills/composio/"' in build
assert overlay["local_composio_skill"] == ".agents/skills/composio"
adapter = next(x for x in overlay["external_adapters"] if x["id"] == "composio")
assert adapter["credential_env"] == "BARS_COMPOSIO_TOKEN"

# Names/presence only. No real token values belong in these repo contracts.
for text in [api, caps, build, source.read_text()]:
    assert "ck_" not in text
    assert "ak_" not in text

print("PASS: official Composio skill + Infisical runtime credential contract")
