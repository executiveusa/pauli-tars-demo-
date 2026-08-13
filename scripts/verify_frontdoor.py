#!/usr/bin/env python3
"""Static contract checks for the BARS 3D front door.

This intentionally verifies claims, wiring names, and safety posture without
pretending that a static test proves the remote runtime is healthy.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "frontdoor.html").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")

required = [
    "BARS — Operator for Trail Mixx",
    'id="scene"',
    'data-action="talk"',
    'data-action="mission"',
    'data-action="trail"',
    'data-action="build"',
    'data-action="jobs"',
    'data-action="status"',
    'getJSON("/api/status")',
    'getJSON("/missions")',
    "NOT CONNECTED YET",
    "prefers-reduced-motion",
    "touchmove",
    "OPEN BARS",
]
missing = [needle for needle in required if needle not in HTML]
assert not missing, f"frontdoor contract missing: {missing}"

# Phase 2 front door is read-only except navigation. Trail Mixx must not write
# until the real adapter is proven in Phase 3.
for forbidden in ('"/brief"', '"/abort"', '"/act"', '"/tools"'):
    assert forbidden not in HTML, f"frontdoor unexpectedly references write endpoint: {forbidden}"

assert not re.search(r"\btars\b", HTML, re.I), "legacy TARS product copy leaked into the BARS front door"
print("BARS front door contract: PASS")

assert '"/agent"' in SERVER and 'frontdoor.html' in SERVER, "server must route public front door and /agent cockpit"
assert '"text/html; charset=utf-8" if name.endswith(".html")' in SERVER, "static HTML must render as text/html"
