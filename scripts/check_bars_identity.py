#!/usr/bin/env python3
"""Fail when legacy TARS identity or rename collateral leaks into BARS."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")

failures: list[str] = []

# Product surface: BARS everywhere the user can see or say the name.
if 'TA<b>R</b>S' in HTML:
    failures.append("legacy TARS wordmark remains in static/index.html")
if re.search(r"\bTARS\b", re.sub(r"<[^>]+>", " ", HTML), re.I):
    failures.append("legacy TARS text remains in rendered HTML copy")
if not re.search(r"const WAKE=.*?bars", HTML, re.I):
    failures.append("wake-word regex does not accept BARS")
if not re.search(r"<title>\s*BARS\b", HTML, re.I):
    failures.append("document title is not BARS")
if 'id="wordmark">BA<b>R</b>S' not in HTML:
    failures.append("visible wordmark is not BARS")

# Catch known substring-collision collateral from TARS -> BARS symbol migration.
if 'sbars' in HTML.lower():
    failures.append("rename collateral changed stars/starfield identifiers to sbars")
if 'id="stars"' not in HTML or '#stars' not in HTML:
    failures.append("starfield identifier was not preserved")

# Docs/runtime public identity.
if re.search(r"^#\s+TARS\b", README, re.M | re.I):
    failures.append("README still leads with TARS")
if 'server_version = "BARS/' not in SERVER:
    failures.append("HTTP server does not identify as BARS")
if 'You are BARS' not in SERVER:
    failures.append("runtime persona is not BARS")

# Legacy names are allowed only as explicit read-only migration fallbacks.
allowed_legacy = {
    'tars-state.json', 'tars-memory.md', 'tars-duplex.json', 'tars-tools.json'
}
legacy_files = set(re.findall(r'tars-[a-z0-9_.-]+', SERVER, re.I))
unexpected = sorted(x for x in legacy_files if x.lower() not in allowed_legacy)
if unexpected:
    failures.append("unexpected legacy tars-* runtime names: " + ", ".join(unexpected))
for canonical in ('bars-state.json', 'bars-memory.md', 'bars-duplex.json', 'bars-tools.json'):
    if canonical not in SERVER:
        failures.append(f"missing canonical runtime path: {canonical}")

if failures:
    print("BARS identity check FAILED:")
    for failure in failures:
        print(f"- {failure}")
    sys.exit(1)

print("BARS identity check passed.")
