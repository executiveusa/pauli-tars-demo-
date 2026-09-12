"""BARS skills wiring: pick the smallest relevant set of vendored skill cards
for a mission brief.

Cards live in skills/library (vendored byte-for-byte from pauli-starnet's
reviewed library, pinned by skills/SOURCE.json - run
scripts/check_skills_sync.py). The selector scores keyword overlap over the
card's name, slug, category and description, returns at most `limit` cards,
and attaches each card's pinned sha256 so a mission package can prove which
reviewed skill it carried.
"""
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
LIBRARY = os.path.join(ROOT, "skills", "library")
MANIFEST = os.path.join(ROOT, "skills", "SOURCE.json")

_TOK = re.compile(r"[a-z0-9]+")
_STOP = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "how", "in", "into", "is", "it", "its", "of", "on", "or",
    "so", "that", "the", "their", "this", "to", "what", "when", "where",
    "which", "who", "will", "with", "you", "your",
))


def _toks(text):
    return {t for t in _TOK.findall((text or "").lower()) if t not in _STOP and len(t) > 2}


def _frontmatter(text):
    """Minimal YAML-frontmatter reader for the flat key/value card headers."""
    meta = {}
    if not text.startswith("---"):
        return meta, text
    end = text.find("\n---", 3)
    if end == -1:
        return meta, text
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta, text[end + 4:].strip()


def load_cards():
    """All vendored cards with pinned hashes from SOURCE.json."""
    manifest = json.load(open(MANIFEST))
    cards = []
    for fn in sorted(os.listdir(LIBRARY)):
        if not fn.endswith(".md"):
            continue
        rel = f"skills/library/{fn}"
        raw = open(os.path.join(LIBRARY, fn), "rb").read()
        meta, body = _frontmatter(raw.decode("utf-8", errors="replace"))
        pinned = manifest["files"].get(rel)
        cards.append({
            "slug": meta.get("slug") or fn[:-3],
            "name": meta.get("name") or fn[:-3],
            "description": meta.get("description", ""),
            "category": meta.get("category", ""),
            "path": rel,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "pinned": pinned,
            "pin_ok": pinned == hashlib.sha256(raw).hexdigest(),
            "body": body,
        })
    return cards


def _score(card, brief_toks):
    name_toks = _toks(card["name"]) | _toks(card["slug"].replace("-", " "))
    desc_toks = _toks(card["description"]) | _toks(card["category"])
    return 3 * len(brief_toks & name_toks) + len(brief_toks & desc_toks)


def select(brief, limit=3):
    """Smallest relevant set: top-scoring cards with real overlap, capped."""
    cards = load_cards()
    bt = _toks(brief)
    scored = [(c, _score(c, bt)) for c in cards]
    scored = [(c, s) for c, s in scored if s > 0]
    scored.sort(key=lambda cs: (-cs[1], cs[0]["slug"]))
    return [c for c, _ in scored[:max(1, int(limit))]]


def mission_skills(brief, limit=3):
    """The pinned record a mission package carries (no bodies)."""
    return [{"slug": c["slug"], "name": c["name"], "path": c["path"],
             "sha256": c["sha256"], "pin_ok": c["pin_ok"]}
            for c in select(brief, limit=limit)]


def skills_block(brief, limit=3, budget=3000):
    """Prompt-ready block of the selected cards' bodies, pinned."""
    cards = select(brief, limit=limit)
    if not cards:
        return ""
    parts, used = [], 0
    for c in cards:
        chunk = f"### Skill: {c['name']} ({c['path']}, sha256 {c['sha256'][:12]})\n{c['body']}"
        if used + len(chunk) > budget:
            break
        parts.append(chunk)
        used += len(chunk)
    if not parts:
        return ""
    return ("\n\nSELECTED SKILL CARDS (the smallest relevant set for this brief, "
            "vendored and pinned from the reviewed library - follow them):\n\n"
            + "\n\n".join(parts))
