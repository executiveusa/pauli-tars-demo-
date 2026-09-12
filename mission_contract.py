"""BARS mission packaging (Heisenberg contract).

Every brief becomes an explicit package before execution:
  objective     what the mission is for (the brief, verbatim)
  done_when     the completion condition the report is judged against
  inputs        brief, optional image, pinned skill set
  allowed       tools the brief activates, skills pinned to the package
  budget/gates  cost bound + cap key, the confirmation that authorized
                execution, paid-mode posture
  receipts      the state-transition + verification evidence the mission
                must emit; missions return updated state per receipt

Text briefs upgrade automatically (default done-when: the bounded report);
callers may pass explicit done_when / allowed_tools overrides through
/brief, which the mission.exec confirmation binds by payload hash.
"""

RECEIPT_FORMAT = ["mission_state", "chat", "chat_attempt", "verification", "report"]

DEFAULT_DONE_WHEN = ("Report delivered: findings specific and honest about "
                     "sources, plus numbered recommended next actions.")


def build_package(brief, kind="OPS", cost_bound=0, cap_key=None,
                  skills=None, tools=None, done_when=None, image=None,
                  paid_mode=False):
    pkg = {
        "objective": (brief or "").strip()[:4000],
        "done_when": (done_when or DEFAULT_DONE_WHEN).strip()[:500],
        "inputs": {
            "brief": (brief or "").strip()[:4000],
            "image": bool(image),
            "skills": list(skills or []),
        },
        "allowed": {
            "tools": list(tools or []),
            "skills": [s.get("slug") for s in (skills or [])],
        },
        "budget": {"cost_bound": cost_bound or 0, "cap_key": cap_key},
        "gates": {
            "confirmation": "mission.exec",
            "outward_actions": "separate act.exec confirmation, never this package",
            "paid_mode": bool(paid_mode),
        },
        "receipt_format": list(RECEIPT_FORMAT),
    }
    return pkg


def validate_package(pkg):
    errs = []
    if not isinstance(pkg, dict):
        return ["package must be an object"]
    if not (pkg.get("objective") or "").strip():
        errs.append("objective required")
    if not (pkg.get("done_when") or "").strip():
        errs.append("done_when required")
    inputs = pkg.get("inputs") or {}
    if not isinstance(inputs, dict) or "brief" not in inputs:
        errs.append("inputs.brief required")
    budget = pkg.get("budget") or {}
    if not isinstance(budget.get("cost_bound", 0), (int, float)) or budget.get("cost_bound", 0) < 0:
        errs.append("budget.cost_bound must be a non-negative number")
    gates = pkg.get("gates") or {}
    if gates.get("confirmation") != "mission.exec":
        errs.append("gates.confirmation must be mission.exec")
    if not pkg.get("receipt_format"):
        errs.append("receipt_format required")
    return errs
