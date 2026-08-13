#!/usr/bin/env python3
"""One-time deterministic TARS -> BARS migration for the active product surface.

This script is intentionally assertion-heavy. It refuses to edit if the inspected source
shape has drifted, which is safer than a blind search/replace on the Python runtime.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
HTML = ROOT / "static" / "index.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


# ----------------------------- backend: preserve legacy state while making BARS canonical
server = SERVER.read_text(encoding="utf-8")

server = replace_once(
    server,
    '''STATE_PATH = os.path.join(ROOT, "tars-state.json")\nMEMORY_PATH = os.path.join(ROOT, "tars-memory.md")\nDUPLEX_PATH = os.path.join(ROOT, "tars-duplex.json")''',
    '''STATE_PATH = os.path.join(ROOT, "bars-state.json")\nMEMORY_PATH = os.path.join(ROOT, "bars-memory.md")\nDUPLEX_PATH = os.path.join(ROOT, "bars-duplex.json")\nLEGACY_STATE_PATH = os.path.join(ROOT, "tars-state.json")\nLEGACY_MEMORY_PATH = os.path.join(ROOT, "tars-memory.md")\nLEGACY_DUPLEX_PATH = os.path.join(ROOT, "tars-duplex.json")\n\ndef _read_path(primary, legacy):\n    return primary if os.path.exists(primary) else (legacy if os.path.exists(legacy) else primary)\n\ndef _migrate_legacy_file(primary, legacy):\n    \"\"\"Copy legacy state once; never delete or overwrite the legacy file.\"\"\"\n    if os.path.exists(primary) or not os.path.exists(legacy):\n        return\n    tmp = None\n    try:\n        fd, tmp = tempfile.mkstemp(prefix=\".bars-migrate-\", dir=ROOT)\n        os.close(fd)\n        shutil.copyfile(legacy, tmp)\n        os.replace(tmp, primary)\n    except Exception:\n        if tmp:\n            try:\n                os.unlink(tmp)\n            except OSError:\n                pass\n\nfor _primary, _legacy in ((STATE_PATH, LEGACY_STATE_PATH),\n                          (MEMORY_PATH, LEGACY_MEMORY_PATH),\n                          (DUPLEX_PATH, LEGACY_DUPLEX_PATH)):\n    _migrate_legacy_file(_primary, _legacy)''',
    "state path block",
)

server = replace_once(
    server,
    '''def duplex_token():\n    try:\n        return json.load(open(DUPLEX_PATH))["token"]\n    except Exception:\n        tok = uuid.uuid4().hex + uuid.uuid4().hex[:8]\n        with open(DUPLEX_PATH, "w") as f:\n            json.dump({"token": tok, "_use": "Bearer token for the OpenAI-compatible "\n                       f"duplex brain on port {DUPLEX_PORT} — see DUPLEX.md"}, f, indent=1)\n        return tok''',
    '''def duplex_token():\n    source = _read_path(DUPLEX_PATH, LEGACY_DUPLEX_PATH)\n    try:\n        tok = json.load(open(source))["token"]\n        if source != DUPLEX_PATH:\n            fd, tmp = tempfile.mkstemp(prefix=".bars-duplex-", dir=ROOT)\n            try:\n                with os.fdopen(fd, "w") as f:\n                    json.dump({"token": tok, "_use": "Bearer token for the OpenAI-compatible "\n                               f"duplex brain on port {DUPLEX_PORT} — see DUPLEX.md"}, f, indent=1)\n                os.replace(tmp, DUPLEX_PATH)\n            except Exception:\n                try:\n                    os.unlink(tmp)\n                except OSError:\n                    pass\n        return tok\n    except Exception:\n        tok = uuid.uuid4().hex + uuid.uuid4().hex[:8]\n        with open(DUPLEX_PATH, "w") as f:\n            json.dump({"token": tok, "_use": "Bearer token for the OpenAI-compatible "\n                       f"duplex brain on port {DUPLEX_PORT} — see DUPLEX.md"}, f, indent=1)\n        return tok''',
    "duplex token migration",
)

server = replace_once(
    server,
    'with open(MEMORY_PATH) as f:\n            tail = f.read()[-2500:]',
    'with open(_read_path(MEMORY_PATH, LEGACY_MEMORY_PATH)) as f:\n            tail = f.read()[-2500:]',
    "memory read fallback",
)
server = replace_once(
    server,
    's = _load_json(STATE_PATH)',
    's = _load_json(_read_path(STATE_PATH, LEGACY_STATE_PATH))',
    "state read fallback",
)
server = replace_once(
    server,
    'TOOLS_PATH = os.path.join(ROOT, "tars-tools.json")',
    'TOOLS_PATH = os.path.join(ROOT, "bars-tools.json")\nLEGACY_TOOLS_PATH = os.path.join(ROOT, "tars-tools.json")\n_migrate_legacy_file(TOOLS_PATH, LEGACY_TOOLS_PATH)',
    "tools path",
)
server = replace_once(
    server,
    'return (_load_json(TOOLS_PATH) or {}).get("installed", {})',
    'return (_load_json(_read_path(TOOLS_PATH, LEGACY_TOOLS_PATH)) or {}).get("installed", {})',
    "tools read fallback",
)

# Internal telemetry/protocol identity: BARS is canonical. These are not state filenames.
server = server.replace('agent="tars"', 'agent="bars"')
server = server.replace('task_id="tars-chat"', 'task_id="bars-chat"')
server = server.replace('"clientInfo": {"name": "tars", "version": "1.0"}',
                        '"clientInfo": {"name": "bars", "version": "1.0"}')
server = server.replace('sys.stderr.write("[tars] %s\\n" % (fmt % args))',
                        'sys.stderr.write("[bars] %s\\n" % (fmt % args))')
server = server.replace('"model": "tars"', '"model": "bars"')
SERVER.write_text(server, encoding="utf-8")

# ----------------------------- frontend: all local symbols and visible identity become BARS
html = HTML.read_text(encoding="utf-8")
html = html.replace("TARS", "BARS").replace("tars", "bars")
html = html.replace("T-A-R-S", "B-A-R-S")
html = replace_once(html, 'id="wordmark">TA<b>R</b>S', 'id="wordmark">BA<b>R</b>S', "wordmark")

# Replace the old speech-recognition aliases with BARS-first aliases while retaining TARS as a
# temporary spoken compatibility alias. This does not expose TARS in visible UI copy.
old_wake = r'''const WAKE=/^(?:hey\s+|okay\s+|ok\s+|so\s+|yo\s+|a\s+)*(?:bars|tarz|tar'?s|tarts?|tarse|tarsh|tarus|taurus|stars?|cars|tas|tar)\b[,.!:?\s]*(.*)$/i;'''
new_wake = r'''const WAKE=/^(?:hey\s+|okay\s+|ok\s+|so\s+|yo\s+|a\s+)*(?:bars|barz|bar'?s|barrs?|bards?|tars|tarz|tar'?s)\b[,.!:?\s]*(.*)$/i;'''
html = replace_once(html, old_wake, new_wake, "wake-word regex")

# Preserve old browser preferences once while all future writes use bars_* keys.
anchor = '''const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));'''
compat = anchor + '''\ntry{\n  [["tars_tour_done","bars_tour_done"],["tars_fold_ideas","bars_fold_ideas"],\n   ["tars_fold_sorties","bars_fold_sorties"]].forEach(([oldKey,newKey])=>{\n    if(localStorage.getItem(newKey)===null&&localStorage.getItem(oldKey)!==null)\n      localStorage.setItem(newKey,localStorage.getItem(oldKey));\n  });\n}catch(e){}'''
html = replace_once(html, anchor, compat, "localStorage compatibility hook")

# UI language follows the BARS persona while the existing API field names stay compatible.
html = html.replace('<span class="hudlabel">HUMOR</span>', '<span class="hudlabel">FLAVOR</span>')
html = html.replace('<span class="hudlabel">HONESTY</span>', '<span class="hudlabel">AUTHENTICITY</span>')
html = html.replace('SETTINGS — HUMOR & HONESTY', 'SETTINGS — FLAVOR & AUTHENTICITY')
html = html.replace('Humor and honesty. Dial them wherever you can handle.',
                    'Flavor and authenticity. Dial them wherever you can handle.')
html = html.replace('BARS ONLINE · HUMOR ', 'BARS ONLINE · FLAVOR ')
html = html.replace(' · HONESTY ${', ' · AUTHENTICITY ${')
HTML.write_text(html, encoding="utf-8")

print("Applied deterministic BARS identity migration.")
