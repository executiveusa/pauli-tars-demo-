#!/bin/sh
# BARS sovereign runtime - full versioned test ledger (local, mock provider, no paid calls)
set -e
cd "$(dirname "$0")/.."
for t in test_bars test_security test_paid test_adversarial test_fourth; do
  echo "===== tests/$t.py ====="
  python3 "tests/$t.py"
done
python3 scripts/check_bars_identity.py
python3 scripts/verify_frontdoor.py
python3 -m py_compile server.py bars_router.py bars_security.py hands.py
echo "ALL SUITES PASS"
