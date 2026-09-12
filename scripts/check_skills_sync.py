#!/usr/bin/env python3
"""Verify the vendored BARS prompt bundle and, optionally, its pinned source."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "skills" / "SOURCE.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    source = json.loads(MANIFEST.read_text(encoding="utf-8"))
    revision = source["revision"]
    repository = source["repository"]
    failures = []
    for path, expected in source["files"].items():
        local = ROOT / path
        if not local.is_file():
            failures.append(f"missing vendored file: {path}")
            continue
        data = local.read_bytes()
        actual = digest(data)
        if actual != expected:
            failures.append(f"hash mismatch for {path}: {actual} != {expected}")
        if args.remote:
            url = f"https://raw.githubusercontent.com/{repository}/{revision}/{path}"
            try:
                remote = urllib.request.urlopen(url, timeout=15).read()
            except Exception as exc:
                failures.append(f"could not read pinned source for {path}: {exc}")
            else:
                if remote != data:
                    failures.append(f"vendored bytes differ from pinned source: {path}")
    if failures:
        print("BARS skills sync check FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    suffix = " and pinned source" if args.remote else ""
    print(f"BARS skills library matches SOURCE.json{suffix} ({revision}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
