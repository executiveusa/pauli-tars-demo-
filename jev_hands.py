"""Contract client for BARS's Jev browser-hands sidecar.

This module is not active until the runtime adapter calls it. The sidecar owns
its TypeSafe credential. A dispatched browser run is never retried here.
"""
import json
import os
import socket
import urllib.parse
import urllib.request

RUNNER_URL = os.environ.get("BARS_JEV_RUNNER_URL", "http://jev-runner:8643").rstrip("/")
TIMEOUT = max(5, min(int(os.environ.get("BARS_JEV_TIMEOUT_SECONDS", "180")), 900))
MAX_STATES = max(1, min(int(os.environ.get("BARS_JEV_MAX_STATES", "200")), 1000))
TERMINAL = {"DONE", "BLOCKED", "FAILED"}


class JevUncertainOutcome(RuntimeError):
    """A run may have acted, but no explicit terminal receipt was observed.

    Callers must not retry this run. Require operator inspection/read-back.
    """
    non_retryable = True

    def __init__(self, reason, states=None):
        super().__init__(f"non-retryable uncertain Jev outcome: {reason}")
        self.reason = reason
        self.states = list(states or [])


def _runner_url(path):
    parsed = urllib.parse.urlparse(RUNNER_URL)
    # Accepted production shape: Docker-internal service DNS. The compose file
    # owns isolation and publishes the runner to the host only on 127.0.0.1.
    if parsed.scheme != "http" or parsed.hostname not in {"jev-runner", "127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("BARS Jev runner must be the isolated service or loopback HTTP")
    return RUNNER_URL + path


def health():
    try:
        with urllib.request.urlopen(_runner_url("/health"), timeout=5) as response:
            body = json.load(response)
            status = response.status
        return {"reachable": status == 200, "ready": bool(body.get("typesafe_key"))}
    except Exception as exc:
        return {"reachable": False, "ready": False, "error": str(exc)[:200]}


def run(url, goal):
    """Dispatch exactly once; return only after explicit DONE/BLOCKED/FAILED."""
    target = urllib.parse.urlparse(str(url or "").strip())
    if target.scheme not in {"http", "https"} or not target.netloc:
        raise ValueError("url must be absolute http(s)")
    goal = " ".join(str(goal or "").split())[:2000]
    if not goal:
        raise ValueError("goal required")
    request = urllib.request.Request(
        _runner_url("/run"),
        data=json.dumps({"url": target.geturl(), "goal": goal}).encode(),
        headers={"content-type": "application/json"}, method="POST")
    states = []
    dispatched = False
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            dispatched = True
            if response.status != 200:
                raise JevUncertainOutcome(f"HTTP {response.status} after dispatch", states)
            for raw in response:
                if len(states) >= MAX_STATES:
                    raise JevUncertainOutcome("state limit exhausted", states)
                try:
                    state = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    raise JevUncertainOutcome("malformed NDJSON", states)
                if not isinstance(state, dict):
                    raise JevUncertainOutcome("NDJSON state is not an object", states)
                states.append(state)
                status = str(state.get("status", "")).upper()
                if status in TERMINAL:
                    return {"ok": status == "DONE", "terminal": state, "states": states}
    except JevUncertainOutcome:
        raise
    except Exception as exc:
        # After urlopen is attempted we cannot prove whether the peer acted.
        # Convert every open/read/protocol/parse failure to a non-retryable
        # uncertain outcome. Explicit terminal returns and our own uncertain
        # exceptions are handled above; local input validation ran earlier.
        raise JevUncertainOutcome(f"transport or stream failure: {type(exc).__name__}", states) from exc
    if dispatched:
        reason = "EOF without terminal state" if states else "EOF without parseable state"
        raise JevUncertainOutcome(reason, states)
    raise JevUncertainOutcome("dispatch outcome unknown", states)
