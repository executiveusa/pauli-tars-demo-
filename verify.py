"""BARS verify loop (constitution section 2: verify before you answer).

Changeable facts - dates, times, prices, statuses, availability - may not be
stated as fact unless grounded. Grounding context for /chat is what the
Commander himself said (stated), the stated/observed memory store, the live
jobs board, and tool results. Ungrounded claims get an explicit hedge before
the reply ships; the hedge names the claims so the Commander always knows
which sentence to trust.

For missions, the judge lane independently reviews the worker's report; a
report only seals when the judge verifies it.
"""
import re

_MONEY = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?\s?(?:usd|dollars|bucks)\b", re.I)
_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b(?:tomorrow|tonight|yesterday|next\s+(?:week|month|year|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?))\b"
    r"|\bthis\s+(?:week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\bon\s+(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b",
    re.I)
_TIME = re.compile(r"\b\d{1,2}:\d{2}\s?(?:am|pm)?\b|\b\d{1,2}\s?(?:am|pm)\b", re.I)
_STATUS = re.compile(
    r"\b(?:is|are|was|were|has\s+been|have\s+been|currently|still|now)\s+"
    r"(?:\w+\s+){0,2}?(?:live|down|up|online|offline|available|unavailable|"
    r"in\s+stock|out\s+of\s+stock|sold\s+out|shipped|deployed|released|"
    r"closed|open|delayed|cancelled|canceled|confirmed|sold)\b", re.I)

_KINDS = (("price", _MONEY), ("date", _DATE), ("time", _TIME), ("status", _STATUS))

_TOK = re.compile(r"[a-z0-9]+")
_STOP = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "has", "have", "i", "in", "is", "it", "its", "of", "on", "or",
    "so", "that", "the", "this", "to", "was", "were", "will", "with", "you",
    "your", "currently", "still", "now",
))


def _toks(text):
    return {t for t in _TOK.findall((text or "").lower()) if t not in _STOP}


def _sentences(text):
    parts = re.split(r"(?<=[.!?\n])\s+", text or "")
    return [p.strip() for p in parts if p.strip()]


def detect_claims(text):
    """Find changeable-fact claims. One claim per matching sentence+kind."""
    claims = []
    for sent in _sentences(text):
        for kind, rx in _KINDS:
            m = rx.search(sent)
            if m:
                claims.append({"kind": kind, "text": m.group(0).strip(),
                               "sentence": sent[:220]})
    return claims


def grounded(claim, context):
    """A claim is grounded when every content token in it - including every
    number - appears in the grounding context (what the Commander stated,
    stated/observed memory, jobs board, tool results)."""
    ct = _toks(context)
    need = _toks(claim["sentence"] if isinstance(claim, dict) else str(claim))
    return bool(need) and need <= ct


def verify_reply(reply, context=""):
    """Ground or hedge changeable-fact claims before the reply ships.
    Returns {"reply", "claims", "hedged", "grounded"}."""
    claims = detect_claims(reply)
    if not claims:
        return {"reply": reply, "claims": 0, "hedged": [], "grounded": 0}
    ungrounded, ok = [], 0
    for c in claims:
        if grounded(c, context):
            ok += 1
        else:
            ungrounded.append(c)
    if not ungrounded:
        return {"reply": reply, "claims": len(claims), "hedged": [], "grounded": ok}
    seen, bits = set(), []
    for c in ungrounded:
        key = (c["kind"], c["text"].lower())
        if key in seen:
            continue
        seen.add(key)
        bits.append(f"{c['kind']} '{c['text']}'")
    note = ("\n\n(Not verified against a live source: " + "; ".join(bits[:4])
            + ". Flagging it instead of stating it - say the word and I'll go check.)")
    return {"reply": reply.rstrip() + note, "claims": len(claims),
            "hedged": [c["text"] for c in ungrounded][:8], "grounded": ok}
