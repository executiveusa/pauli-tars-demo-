#!/bin/sh
# BARS sovereign runtime - full versioned test ledger (local, mock provider, no paid calls)
set -e
rm -rf /tmp/v7-data /tmp/v7-deploy /tmp/v6-data /tmp/v6-rec /tmp/v6-deploy /tmp/v5-data /tmp/v5-rec /tmp/v5-deploy /tmp/barsdata2 /tmp/adv-data /tmp/v3-data /tmp/v4-* /tmp/adv-deploy 2>/dev/null || true
cd "$(dirname "$0")/.."
for t in test_bars test_security test_paid test_adversarial test_fourth test_fifth test_sixth test_seventh test_eighth test_ninth test_tenth test_memory_v2 test_verify_loop test_tool_contracts test_skills_wiring test_mission_packaging test_composio_runtime_contract test_terabithia_adapter; do
  echo "===== tests/$t.py ====="
  pkill -f mock_provider.py 2>/dev/null || true; pkill -f "python3 server.py" 2>/dev/null || true; sleep 0.5
  python3 "tests/$t.py"
done
python3 tests/test_prompts.py
python3 scripts/check_skills_sync.py
python3 scripts/check_bars_identity.py
python3 scripts/verify_frontdoor.py
bash tests/test_deploy_docker.sh
python3 scripts/check_release_gate.py
python3 -m py_compile server.py bars_router.py bars_security.py hands.py
echo "ALL SUITES PASS"
