#!/usr/bin/env python3
"""Pin/install upstream Hermes and extract Bambu's custom skill overlay.

Dry-run by default. Pass --apply to mutate the machine.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "hermes" / "SOURCES.json"


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def ensure_checkout(url: str, sha: str, target: Path) -> None:
    if not (target / ".git").exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--no-checkout", url, str(target)])
    run(["git", "fetch", "--depth", "1", "origin", sha], cwd=target)
    run(["git", "checkout", "--detach", sha], cwd=target)
    got = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    if got != sha:
        raise SystemExit(f"pin mismatch for {target}: expected {sha}, got {got}")


def load_registry(overlay: Path, rel: str) -> dict:
    path = (overlay / rel).resolve()
    if not path.is_file() or overlay.resolve() not in path.parents:
        raise SystemExit(f"overlay registry missing or escaped checkout: {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit("custom skill registry must be a JSON object")
    return data


def registry_entries(registry: dict) -> list[dict]:
    # Current Pauli registry has used both list-style and object-style layouts
    # over time; accept either without guessing paths.
    raw = registry.get("skills", registry)
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        out = []
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", key)
                out.append(item)
        return out
    raise SystemExit("unsupported SKILL_REGISTRY.json shape")


def extract_skills(overlay: Path, registry_rel: str, dest_root: Path, *, replace: bool) -> int:
    registry_path = overlay / registry_rel
    registry = load_registry(overlay, registry_rel)
    entries = registry_entries(registry)
    dest_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())

    for item in entries:
        if item.get("enabled") is False:
            continue
        rel = item.get("path") or item.get("source") or item.get("dir")
        if not rel:
            continue
        src = (overlay / str(rel)).resolve()
        if overlay.resolve() not in src.parents or not src.is_dir():
            print(f"! skip registry entry without directory: {rel}")
            continue
        if not (src / "SKILL.md").is_file():
            print(f"! skip registry entry without SKILL.md: {rel}")
            continue
        slug = str(item.get("id") or item.get("name") or src.name).strip().replace("/", "-")
        if not slug or slug in {".", ".."}:
            continue
        dst = dest_root / slug
        if dst.exists():
            if not replace:
                print(f"= keep existing {dst}")
                continue
            backup = dest_root / f".{slug}.bars-backup-{stamp}"
            print(f"~ backup {dst} -> {backup}")
            dst.rename(backup)
        shutil.copytree(src, dst, symlinks=False)
        copied += 1
        print(f"+ skill {slug} <- {rel}")

    shutil.copy2(registry_path, dest_root / "SKILL_REGISTRY.json")
    return copied


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform installation/extraction")
    ap.add_argument("--replace-overlay", action="store_true",
                    help="backup and replace existing Pauli overlay skills")
    ap.add_argument("--runtime-dir", default=str(ROOT / ".runtime" / "hermes-upstream"))
    ap.add_argument("--overlay-dir", default=str(ROOT / ".runtime" / "hermes-overlay"))
    ap.add_argument("--hermes-home", default=str(Path.home() / ".hermes"))
    args = ap.parse_args()

    pins = json.loads(SOURCES.read_text())
    runtime = pins["runtime"]
    overlay = pins["overlay"]
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    overlay_dir = Path(args.overlay_dir).expanduser().resolve()
    hermes_home = Path(args.hermes_home).expanduser().resolve()

    print("BARS -> Hermes kernel bootstrap")
    print(f"runtime {runtime['repository']} @ {runtime['commit']}")
    print(f"overlay {overlay['repository']} @ {overlay['commit']}")
    print(f"HERMES_HOME {hermes_home}")
    if not args.apply:
        print("DRY RUN: pass --apply to install exact pins and extract the custom skill overlay.")
        return 0

    if shutil.which("git") is None:
        raise SystemExit("git is required")

    ensure_checkout(runtime["repository"], runtime["commit"], runtime_dir)
    ensure_checkout(overlay["repository"], overlay["commit"], overlay_dir)

    installer = runtime_dir / "scripts" / "install.sh"
    if not installer.is_file():
        raise SystemExit(f"upstream installer missing: {installer}")
    run([
        "bash", str(installer),
        "--commit", runtime["commit"],
        "--force-commit",
        "--skip-setup",
        "--non-interactive",
        "--dir", str(runtime_dir),
        "--hermes-home", str(hermes_home),
    ], cwd=runtime_dir)

    hermes = shutil.which("hermes") or str(hermes_home / "bin" / "hermes")
    if not Path(hermes).exists() and shutil.which(hermes) is None:
        raise SystemExit("Hermes install completed but executable was not found")

    profiles = subprocess.run(
        [hermes, "profile", "list"], text=True, capture_output=True, check=True
    ).stdout
    if not any(line.strip().lstrip("*").strip() == "bars" for line in profiles.splitlines()):
        run([
            hermes, "profile", "create", "bars", "--no-alias",
            "--description",
            "BARS artist-facing operator: creative products, media, web, code, apps, and governed execution.",
        ])

    profile_home = hermes_home / "profiles" / "bars"
    skills_base = profile_home / "skills" if profile_home.exists() else hermes_home / "skills"
    dest = skills_base / "pauli"
    copied = extract_skills(
        overlay_dir, overlay["registry"], dest, replace=args.replace_overlay
    )

    print(f"OK: Hermes runtime pinned; {copied} custom skills extracted into {dest}")
    print("NEXT: configure the MCP servers from hermes/bars-mcp.example.yaml, then run:")
    print("  BARS_HERMES_ENABLED=1 python3 bars_hermes.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
