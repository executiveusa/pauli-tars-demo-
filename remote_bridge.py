#!/usr/bin/env python3
"""Outbound-only remote mission bridge for BARS.

Polls Terabithia for a queued BARS mission, claims it, dispatches it to the
local BARS runtime, polls local completion, and reports truthful evidence back.
No inbound Internet listener is opened on the user's computer.
"""
import json
import os
import socket
import time
import urllib.error
import urllib.request

REMOTE = os.environ.get("TERABITHIA_REMOTE_URL", "").rstrip("/")
TOKEN = os.environ.get("TERABITHIA_API_KEY", "")
LOCAL = os.environ.get("BARS_LOCAL_URL", "http://127.0.0.1:4321").rstrip("/")
NODE_ID = os.environ.get("BARS_NODE_ID", socket.gethostname() or "bars-node")
POLL_SECONDS = max(1.0, float(os.environ.get("BARS_REMOTE_POLL_SECONDS", "2")))
LOCAL_TIMEOUT_SECONDS = max(30, int(os.environ.get("BARS_REMOTE_MISSION_TIMEOUT", "900")))

TERMINAL_DONE = {"DONE", "COMPLETED", "COMPLETE", "SUCCESS"}
TERMINAL_FAILED = {"FAILED", "ERROR"}
TERMINAL_CANCELLED = {"ABORTED", "CANCELLED", "CANCELED"}


def request(url, method="GET", payload=None, timeout=20):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if url.startswith(REMOTE) and TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw or "{}")
        except Exception:
            body = {"error": raw[:300]}
        return exc.code, body


def report(mission_id, status, **extra):
    payload = {"mission_id": mission_id, "node_id": NODE_ID, "status": status}
    payload.update(extra)
    return request(f"{REMOTE}/api/v1/operators/bars/report", "POST", payload)


def normalize_local_status(raw):
    s = str(raw or "").strip().upper()
    if s in TERMINAL_DONE:
        return "done"
    if s in TERMINAL_FAILED:
        return "failed"
    if s in TERMINAL_CANCELLED:
        return "cancelled"
    return "working"


def dispatch_remote(mission):
    mission_id = mission["mission_id"]
    intent = str(mission.get("user_intent") or "").strip()
    if not intent:
        report(mission_id, "failed", summary="Remote mission had no user_intent.", failures=["missing user_intent"])
        return

    code, dispatched = request(f"{LOCAL}/brief", "POST", {"brief": intent}, timeout=30)
    bars_id = str(dispatched.get("id") or "") if isinstance(dispatched, dict) else ""
    if code >= 300 or not bars_id:
        report(mission_id, "failed", summary="Local BARS dispatch failed.", failures=[str(dispatched)[:500]])
        return

    report(
        mission_id,
        "working",
        bars_mission_id=bars_id,
        summary=f"BARS accepted the mission as {bars_id}.",
        evidence=[{"type": "external_state", "ref": f"bars://mission/{bars_id}", "summary": "local BARS mission receipt"}],
    )

    started = time.time()
    while time.time() - started < LOCAL_TIMEOUT_SECONDS:
        time.sleep(POLL_SECONDS)
        code, local = request(f"{LOCAL}/mission/{bars_id}", timeout=15)
        if code >= 300:
            continue
        state = normalize_local_status(local.get("status"))
        summary = str(local.get("report") or local.get("debrief") or "").strip()
        evidence = [{"type": "external_state", "ref": f"bars://mission/{bars_id}", "summary": str(local.get("status") or state)}]
        if summary:
            evidence.append({"type": "artifact", "ref": f"bars://mission/{bars_id}/report", "summary": summary[:500]})
        if state == "working":
            continue
        failures = [summary[:1000]] if state == "failed" and summary else []
        report(mission_id, state, bars_mission_id=bars_id, summary=summary[:4000] or f"BARS mission {bars_id} ended as {state}.", evidence=evidence, failures=failures)
        return

    report(
        mission_id,
        "failed",
        bars_mission_id=bars_id,
        summary="Local BARS mission exceeded the remote bridge timeout.",
        failures=[f"timeout after {LOCAL_TIMEOUT_SECONDS}s"],
        evidence=[{"type": "external_state", "ref": f"bars://mission/{bars_id}", "summary": "timeout"}],
    )


def run_once():
    if not REMOTE or not TOKEN:
        raise RuntimeError("TERABITHIA_REMOTE_URL and TERABITHIA_API_KEY are required; bridge fails closed.")
    code, mission = request(
        f"{REMOTE}/api/v1/operators/bars/claim",
        "POST",
        {"node_id": NODE_ID},
        timeout=20,
    )
    if code == 204:
        return False
    if code != 200:
        raise RuntimeError(f"claim failed HTTP {code}: {str(mission)[:300]}")
    dispatch_remote(mission)
    return True


def main():
    if not REMOTE or not TOKEN:
        raise SystemExit("BARS remote bridge disabled: set TERABITHIA_REMOTE_URL and TERABITHIA_API_KEY.")
    print(f"[BARS remote] outbound bridge online as {NODE_ID}; polling {REMOTE}")
    while True:
        try:
            worked = run_once()
            if not worked:
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"[BARS remote] {str(exc)[:300]}")
            time.sleep(min(10.0, POLL_SECONDS * 2))


if __name__ == "__main__":
    main()
