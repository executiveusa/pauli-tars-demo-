#!/usr/bin/env python3
"""Apply the reviewed BARS front-door fixes deterministically.

One-time migration helper for PR #4. It is intentionally strict: if an expected
old shape is absent and the new shape is not already present, fail instead of
silently editing the wrong code.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "static" / "frontdoor.html"
VERIFY = ROOT / "scripts" / "verify_frontdoor.py"
SERVER = ROOT / "server.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"expected pattern missing: {label}")
    return text.replace(old, new, 1)


front = FRONT.read_text(encoding="utf-8")

# Landing page is the public front door; the existing full cockpit moves to
# /agent without duplicating its mission/backend logic.
front = front.replace('href="/"', 'href="/agent"')

front = replace_once(
    front,
    'async function getJSON(path){const r=await fetch(path,{cache:"no-store"});let j={};try{j=await r.json()}catch(e){}if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);return j}',
    'async function getJSON(path){const r=await fetch(path,{cache:"no-store"});let j;try{j=await r.json()}catch(e){throw new Error(r.ok?"Invalid JSON response":`HTTP ${r.status}`)}if(!r.ok)throw new Error(j&&j.error||`HTTP ${r.status}`);return j}',
    "strict JSON helper",
)

# TALK / MISSION / BUILD should do the obvious thing in one tap.
old_cockpit = 'function cockpit(label){showCard(label,"This control opens the existing BARS agent experience. The landing page does not duplicate mission logic.","Real actions remain in the governed backend.",\'<a class="go" href="/agent">OPEN BARS ↗</a>\')}'
front = replace_once(
    front,
    old_cockpit,
    'function cockpit(){window.location.assign("/agent")}',
    "direct cockpit navigation",
)

# WebGL may fail even if THREE loaded. Keep the semantic controls usable.
front = replace_once(
    front,
    'const rig=$("#rig"),cv=$("#scene"),renderer=new THREE.WebGLRenderer({canvas:cv,alpha:true,antialias:true});',
    'const rig=$("#rig"),cv=$("#scene");let renderer;try{renderer=new THREE.WebGLRenderer({canvas:cv,alpha:true,antialias:true})}catch(e){showCard("3D UNAVAILABLE","This device could not start WebGL.","The controls still work without the visual.");return}',
    "WebGL fallback",
)

front = replace_once(
    front,
    'glow.intensity=1.05+(Math.sin(t*3)*.15);',
    'glow.intensity=reduced?1.05:1.05+(Math.sin(t*3)*.15);',
    "reduced-motion glow",
)

FRONT.write_text(front, encoding="utf-8")

verify = VERIFY.read_text(encoding="utf-8")
verify = replace_once(
    verify,
    'from pathlib import Path\n',
    'from pathlib import Path\nimport re\n',
    "verifier regex import",
)
verify = verify.replace('    \'fetch("/api/status"\',\n', '    \'getJSON("/api/status")\',\n')
verify = verify.replace('    \'fetch("/missions"\',\n', '    \'getJSON("/missions")\',\n')
verify = replace_once(
    verify,
    'for forbidden in (\'fetch("/brief"\', \'fetch("/abort"\', \'fetch("/act"\', \'fetch("/tools"\'):\n    assert forbidden not in HTML, f"frontdoor unexpectedly performs write action: {forbidden}"',
    'for forbidden in (\'"/brief"\', \'"/abort"\', \'"/act"\', \'"/tools"\'):\n    assert forbidden not in HTML, f"frontdoor unexpectedly references write endpoint: {forbidden}"',
    "write endpoint check",
)
verify = replace_once(
    verify,
    'assert "TARS" not in HTML, "legacy TARS product copy leaked into the BARS front door"',
    'assert not re.search(r"\\btars\\b", HTML, re.I), "legacy TARS product copy leaked into the BARS front door"',
    "case-insensitive identity check",
)
# The landing/cockpit routing itself is part of the contract.
if 'SERVER = (ROOT / "server.py").read_text' not in verify:
    verify = verify.replace(
        'HTML = (ROOT / "static" / "frontdoor.html").read_text(encoding="utf-8")\n',
        'HTML = (ROOT / "static" / "frontdoor.html").read_text(encoding="utf-8")\nSERVER = (ROOT / "server.py").read_text(encoding="utf-8")\n',
        1,
    )
    verify += '\nassert \'"/agent"\' in SERVER and \'frontdoor.html\' in SERVER, "server must route public front door and /agent cockpit"\n'
    verify += 'assert \'"text/html; charset=utf-8" if name.endswith(".html")\' in SERVER, "static HTML must render as text/html"\n'

VERIFY.write_text(verify, encoding="utf-8")

server = SERVER.read_text(encoding="utf-8")
server = replace_once(
    server,
    'if path in ("/", "/index.html"):\n            try:',
    'if path in ("/", "/frontdoor", "/frontdoor.html", "/agent", "/agent/", "/index.html"):\n            page = "frontdoor.html" if path in ("/", "/frontdoor", "/frontdoor.html") else "index.html"\n            try:',
    "root/frontdoor/agent routes",
)
server = replace_once(
    server,
    'with open(os.path.join(STATIC, "index.html"), "rb") as f:\n                    body = f.read()',
    'with open(os.path.join(STATIC, page), "rb") as f:\n                    body = f.read()',
    "selected HTML page",
)
server = replace_once(
    server,
    'self._json({"error": "index.html missing"}, 500)',
    'self._json({"error": f"{page} missing"}, 500)',
    "page-aware error",
)
server = replace_once(
    server,
    '"text/css" if name.endswith(".css") else "application/octet-stream"',
    '"text/css" if name.endswith(".css") else \\\n                    "text/html; charset=utf-8" if name.endswith(".html") else "application/octet-stream"',
    "static HTML content type",
)
SERVER.write_text(server, encoding="utf-8")

print("front-door review fixes applied")
