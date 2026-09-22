from pathlib import Path
import re
w=Path('.github/workflows/browser-hands-page-gate.yml').read_text()
for repo,sha in {
 'browser-use/stress-tests':'b3600b683ec97236866d77e31200fa24ec8c8f3f',
 'browser-use/benchmark':'421390ea7fa4708f3d89d7695f9a16debb861daf',
}.items():
 assert repo in w and sha in w
assert '--depth 1' in w and 'git clone' in w
assert not re.search(r'^\s*cp\s', w, re.M)
assert 'vendor into' not in w.lower()
assert '"browser-use": FrameworkInfo(' in w
assert 'STRESS_URL: http://127.0.0.1:4172/index.html' in w
assert 'scripts/check_browser_hands_external.py' in w and 'tests/run_all.sh' in w
assert Path('tests/browser_hands/page_gate.mjs').exists()
print('BARS external browser-hands gate contract: PASS')
