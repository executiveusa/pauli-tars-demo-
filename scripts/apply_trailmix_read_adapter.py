#!/usr/bin/env python3
"""Wire the read-only Trail Mixx adapter into BARS deterministically."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"expected pattern missing: {label}")
    return text.replace(old, new, 1)


server = SERVER.read_text(encoding="utf-8")
server = replace_once(
    server,
    "import hue\n",
    "import hue\nimport trailmix\n",
    "trailmix import",
)
server = replace_once(
    server,
    '        "hue": cfg.get("hue", {}),\n    }',
    '        "hue": cfg.get("hue", {}),\n        "trail_mixx": cfg.get("trail_mixx", {}),\n    }',
    "trail mixx config",
)
server = replace_once(
    server,
    '        elif path == "/api/status":\n            spend = {}',
    '        elif path == "/api/trailmix/nowplaying":\n            try:\n                result = trailmix.now_playing(CONFIG.get("trail_mixx", {}))\n                self._json(result, 200 if result.get("connected") else 503)\n            except trailmix.TrailMixxError as exc:\n                self._json({"configured": bool(CONFIG.get("trail_mixx", {}).get("base_url")),\n                            "connected": False,\n                            "source": "trail_mixx_public_nowplaying",\n                            "stations": [],\n                            "error": str(exc)[:240]}, 502)\n        elif path == "/api/status":\n            spend = {}',
    "read-only nowplaying endpoint",
)
server = replace_once(
    server,
    '                        "hue": hue.status()["state"],\n                        "memory": os.path.exists(MEMORY_PATH),',
    '                        "hue": hue.status()["state"],\n                        "trail_mixx": trailmix.status(CONFIG.get("trail_mixx", {})),\n                        "memory": os.path.exists(MEMORY_PATH),',
    "status config truth",
)
SERVER.write_text(server, encoding="utf-8")
print("Trail Mixx read adapter wired")
