"""BARS structured memory v2.

Replaces the flat-file tail as the source of prompt memory with:

- one fact per record (JSONL), each carrying a constitution provenance tag:
  [stated] (the Commander said it), [observed] (seen in a record),
  [inferred] (BARS concluded it - weakest tier, re-check before relying)
- keyword + recency retrieval, so facts relevant to the current message reach
  the prompt instead of merely the most recent ones
- server-side chat transcripts (per-session JSONL), so conversation history
  no longer depends on what the client chooses to send and never-re-ask is
  enforceable from server state

Stdlib only. All state lives under BARS_DATA_DIR/memory/.
"""
import hashlib
import json
import os
import re
import threading
import time
import uuid

PROVENANCE = ("stated", "observed", "inferred")

_LOCK = threading.Lock()
_DIR = None

_STOP = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "me",
    "my", "of", "on", "or", "our", "she", "so", "that", "the", "their",
    "them", "they", "this", "to", "us", "was", "we", "what", "when", "where",
    "which", "who", "will", "with", "you", "your",
))
_TOK = re.compile(r"[a-z0-9']+")
_FLAT_LINE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*(.+)$")


def init(data_dir):
    """Point the store at BARS_DATA_DIR; creates memory/ lazily on write."""
    global _DIR
    _DIR = os.path.join(data_dir, "memory")


def _ready():
    if _DIR is None:
        raise RuntimeError("memory_store.init() not called")


def _facts_path():
    return os.path.join(_DIR, "facts.jsonl")


def _tx_dir():
    return os.path.join(_DIR, "transcripts")


def _toks(text):
    return {t for t in _TOK.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


def add_fact(text, provenance="stated", source="remember"):
    """Append one provenance-tagged fact. Returns the record."""
    _ready()
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("empty fact")
    if provenance not in PROVENANCE:
        raise ValueError(f"provenance must be one of {PROVENANCE}")
    rec = {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "prov": provenance,
        "src": str(source or "")[:80],
        "t": time.time(),
        "hits": 0,
    }
    with _LOCK:
        os.makedirs(_DIR, exist_ok=True)
        with open(_facts_path(), "a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return rec


def load_facts():
    _ready()
    facts = []
    try:
        with open(_facts_path()) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("prov") in PROVENANCE and rec.get("text"):
                        facts.append(rec)
    except FileNotFoundError:
        pass
    return facts


def _score(rec, query_toks, now):
    overlap = len(query_toks & _toks(rec["text"]))
    if query_toks and overlap == 0:
        return 0.0
    age_days = max(0.0, (now - float(rec.get("t", 0))) / 86400.0)
    recency = 1.0 / (1.0 + age_days / 14.0)          # ~2-week halving feel
    prov_w = {"stated": 0.3, "observed": 0.2, "inferred": 0.0}[rec["prov"]]
    hits = min(int(rec.get("hits", 0)), 5) * 0.05
    return overlap * 2.0 + recency + prov_w + hits


def recall(query="", limit=6, bump=True):
    """Rank facts by relevance to the query, then recency. Empty query ranks
    by recency alone (voice/realtime path)."""
    facts = load_facts()
    if not facts:
        return []
    now = time.time()
    qt = _toks(query)
    if not qt:
        # no query context (voice/realtime path): pure recency
        facts.sort(key=lambda f: f.get("t", 0), reverse=True)
        scored = [(f, 1.0) for f in facts]
    else:
        scored = [(f, _score(f, qt, now)) for f in facts]
    scored = [(f, s) for f, s in scored if s > 0]
    scored.sort(key=lambda fs: (fs[1], fs[0].get("t", 0)), reverse=True)
    out = [f for f, _ in scored[:max(1, int(limit))]]
    if bump and out:
        ids = {f["id"] for f in out}
        with _LOCK:
            try:
                lines = []
                with open(_facts_path()) as f:
                    for line in f:
                        if line.strip():
                            try:
                                rec = json.loads(line)
                            except ValueError:
                                lines.append(line)
                                continue
                            if rec.get("id") in ids:
                                rec["hits"] = int(rec.get("hits", 0)) + 1
                            lines.append(json.dumps(rec, separators=(",", ":")) + "\n")
                fd, tmp = _tmp()
                with os.fdopen(fd, "w") as f:
                    f.writelines(lines)
                os.replace(tmp, _facts_path())
            except FileNotFoundError:
                pass
    return out


def _tmp():
    import tempfile
    return tempfile.mkstemp(prefix=".facts-", dir=_DIR)


def facts_block(query="", limit=6, budget=2000):
    """Prompt-ready memory block with visible provenance tags."""
    recs = recall(query, limit=limit)
    if not recs:
        return ""
    lines = []
    used = 0
    for r in recs:
        day = time.strftime("%Y-%m-%d", time.gmtime(float(r.get("t", 0))))
        line = f"- [{r['prov']}] ({day}) {r['text']}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    return ("\n\nYOUR LONG-TERM MEMORY (provenance-tagged facts - [stated] the "
            "Commander said, [observed] seen in a record, [inferred] you "
            "concluded; re-check inferred before relying on it; use what is "
            "relevant, never re-ask what is already here):\n" + "\n".join(lines))


def migrate_flat(md_path, source="migration"):
    """One-time import of flat '- [date] text' lines as [stated] facts
    (the flat file only ever held things the Commander said to remember).
    Idempotent: lines already present as facts are skipped."""
    _ready()
    try:
        with open(md_path) as f:
            raw = f.read()
    except Exception:
        return 0
    existing = {r["text"] for r in load_facts()}
    added = 0
    for line in raw.splitlines():
        m = _FLAT_LINE.match(line.strip())
        text = (m.group(2) if m else line.strip().lstrip("- ").strip())[:500]
        if not text or text in existing:
            continue
        rec = add_fact(text, provenance="stated", source=source)
        if m:
            try:
                rec["t"] = time.mktime(time.strptime(m.group(1), "%Y-%m-%d"))
            except Exception:
                pass
        existing.add(text)
        added += 1
    return added


# ------------------------------------------------------- chat transcripts

def _tx_path(session):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(session or ""))[:40]
    if not sid:
        sid = hashlib.sha256(str(session).encode()).hexdigest()[:16]
    return os.path.join(_tx_dir(), sid + ".jsonl")


def append_turn(session, role, content):
    _ready()
    if role not in ("user", "assistant"):
        raise ValueError("role must be user or assistant")
    content = str(content or "")[:2000]
    if not content.strip():
        return None
    rec = {"role": role, "content": content, "t": time.time()}
    with _LOCK:
        os.makedirs(_tx_dir(), exist_ok=True)
        with open(_tx_path(session), "a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return rec


def transcript(session, limit=16):
    _ready()
    turns = []
    try:
        with open(_tx_path(session)) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        turns.append(json.loads(line))
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return turns[-max(1, int(limit)):]


def sessions():
    _ready()
    try:
        return sorted(f[:-6] for f in os.listdir(_tx_dir()) if f.endswith(".jsonl"))
    except FileNotFoundError:
        return []
