#!/usr/bin/env python3
"""Terabithia adapter sidecar for BARS.

Keeps the existing BARS cockpit/server untouched while exposing a narrow,
standard fleet contract on port 4324.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BARS_URL = os.environ.get("BARS_LOCAL_URL", "http://127.0.0.1:4321").rstrip("/")
PORT = int(os.environ.get("BARS_TERABITHIA_PORT", "4324"))
# BARS owns two fleet routes: "operator" (computer use, media) and, since the 2026-09-26 split that
# made Pi personal-only, "engineering" (code, repos, PRs, builds).
ACCEPTED_ROUTES = {"operator", "engineering"}
# Engineering missions run on the engineering/pauli-control bridge (repo-scoped coding jobs), not the
# operator mission path, which has no repo access. Unset URL => engineering is refused, never faked.
CONTROL_URL = os.environ.get("PAULI_CONTROL_URL", "").rstrip("/")
ENGINEERING_MODES = {"plan", "read", "write", "ship"}
ENG_PREFIX = "eng-"


def _token_ok(header_value):
    """Terabithia sends Authorization: Bearer $BARS_TOKEN. When BARS_TERABITHIA_TOKEN is set it is
    required; the adapter binds loopback, so an unset token keeps today's behavior."""
    expected = os.environ.get("BARS_TERABITHIA_TOKEN", "").strip()
    if not expected:
        return True
    raw = str(header_value or "")
    provided = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
    a = hashlib.sha256(provided.encode()).digest()
    b = hashlib.sha256(expected.encode()).digest()
    return bool(provided) and hmac.compare_digest(a, b)


def _request(path, method="GET", body=None, timeout=15):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BARS_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8") or "{}")


def _control(path, method="GET", body=None, timeout=15):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        CONTROL_URL + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('PAULI_CONTROL_TOKEN', '')}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _engineering_request(mission):
    """Map a Terabithia engineering mission onto a pauli-control /run request. Plan mode unless the
    mission asks otherwise; the bridge itself still refuses write/ship unless ALLOW_WRITE/ALLOW_SHIP."""
    context = mission.get("context") if isinstance(mission.get("context"), dict) else {}
    mode = str(mission.get("mode") or context.get("mode") or "plan")
    if mode not in ENGINEERING_MODES:
        raise ValueError("mode must be plan, read, write or ship")
    return {
        "task": mission["user_intent"],
        "mode": mode,
        "repo": str(mission.get("repo") or context.get("repo") or "."),
    }


def _terminal(status):
    raw = str(status or "").strip().upper()
    if raw in {"DONE", "COMPLETED", "COMPLETE", "SUCCESS"}:
        return "done"
    if raw in {"FAILED", "ERROR", "ABORTED", "CANCELLED"}:
        return "failed" if raw not in {"ABORTED", "CANCELLED"} else "cancelled"
    return "working"


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        try:
            size = int(self.headers.get("Content-Length", "0") or 0)
            if size <= 0 or size > 1_000_000:
                return {}
            return json.loads(self.rfile.read(size).decode("utf-8"))
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            try:
                status = _request("/api/status", timeout=5)
                self._json({
                    "ok": bool(status.get("ok")),
                    "agent": "bars",
                    "role": "operator",
                    "bars": status,
                }, 200 if status.get("ok") else 503)
            except Exception as exc:
                self._json({"ok": False, "agent": "bars", "error": str(exc)[:300]}, 503)
            return

        prefix = "/api/terabithia/status/"
        if path.startswith(prefix) and not _token_ok(self.headers.get("Authorization")):
            self._json({"error": "unauthorized"}, 401)
            return
        if path.startswith(prefix):
            bars_mission_id = path[len(prefix):].strip()
            if not bars_mission_id or "/" in bars_mission_id or ".." in bars_mission_id:
                self._json({"error": "invalid mission id"}, 400)
                return
            if bars_mission_id.startswith(ENG_PREFIX):
                self._engineering_status(bars_mission_id)
                return
            try:
                mission = _request(f"/mission/{bars_mission_id}", timeout=10)
                mapped = _terminal(mission.get("status"))
                report = (mission.get("report") or mission.get("debrief") or "").strip()
                evidence = [
                    {"type": "external_state", "ref": f"bars://mission/{bars_mission_id}", "summary": str(mission.get("status") or "BARS state")}
                ]
                if report:
                    evidence.append({"type": "artifact", "ref": f"bars://mission/{bars_mission_id}/report", "summary": report[:500]})
                self._json({
                    "bars_mission_id": bars_mission_id,
                    "status": mapped,
                    "raw_status": mission.get("status"),
                    "summary": report[:2000] or f"BARS mission {bars_mission_id} is {mission.get('status', 'in progress')}.",
                    "evidence": evidence,
                    "failures": [report[:500]] if mapped == "failed" and report else [],
                    "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if mapped in {"done", "failed", "cancelled"} else None,
                })
            except urllib.error.HTTPError as exc:
                self._json({"error": f"BARS returned HTTP {exc.code}"}, 404 if exc.code == 404 else 502)
            except Exception as exc:
                self._json({"error": str(exc)[:300]}, 502)
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.split("?", 1)[0].rstrip("/") != "/api/terabithia/invoke":
            self._json({"error": "not found"}, 404)
            return

        if not _token_ok(self.headers.get("Authorization")):
            self._json({"error": "unauthorized"}, 401)
            return

        mission = self._body()
        required = ("mission_id", "request_id", "conversation_id", "trace_id", "target", "route", "user_intent")
        missing = [key for key in required if not str(mission.get(key, "")).strip()]
        if missing:
            self._json({"error": "missing required mission fields", "fields": missing}, 400)
            return
        route = mission.get("route")
        if mission.get("target") != "bars" or not isinstance(route, str) or route not in ACCEPTED_ROUTES:
            self._json({"error": "BARS only accepts operator or engineering missions targeted to bars"}, 409)
            return
        if route == "engineering":
            self._invoke_engineering(mission)
            return

        started = time.time()
        try:
            dispatched = _request("/brief", "POST", {"brief": mission["user_intent"]}, timeout=30)
            if not dispatched.get("id"):
                raise RuntimeError(dispatched.get("error") or "BARS did not return a mission id")
            bars_mission_id = str(dispatched["id"])
            self._json({
                "mission_id": mission["mission_id"],
                "request_id": mission["request_id"],
                "trace_id": mission["trace_id"],
                "agent_id": "bars",
                "status": "working",
                "summary": f"BARS accepted the {mission['route']} mission as {bars_mission_id}.",
                "artifacts": [],
                "evidence": [
                    {"type": "external_state", "ref": f"bars://mission/{bars_mission_id}", "summary": "BARS mission receipt"},
                    {"type": "trace", "ref": f"trace://{mission['trace_id']}"},
                ],
                "failures": [],
                "human_blocker": None,
                "handoff": None,
                "memory_candidate": None,
                "next_action": f"Poll /api/terabithia/status/{bars_mission_id} for completion evidence.",
                "completed_at": None,
                "runtime": {"bars_mission_id": bars_mission_id, "dispatch_ms": int((time.time() - started) * 1000)},
            }, 202)
        except urllib.error.HTTPError as exc:
            self._json({"error": f"BARS returned HTTP {exc.code}"}, 502)
        except Exception as exc:
            self._json({
                "mission_id": mission.get("mission_id"),
                "request_id": mission.get("request_id"),
                "trace_id": mission.get("trace_id"),
                "agent_id": "bars",
                "status": "failed",
                "summary": "BARS dispatch failed.",
                "artifacts": [],
                "evidence": [{"type": "trace", "ref": f"trace://{mission.get('trace_id', 'unknown')}"}],
                "failures": [str(exc)[:500]],
                "human_blocker": None,
                "handoff": None,
                "memory_candidate": None,
                "next_action": "Check the BARS cockpit/server and retry through Terabithia.",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, 502)

    def _envelope(self, mission, status, summary, code, **extra):
        payload = {
            "mission_id": mission.get("mission_id"),
            "request_id": mission.get("request_id"),
            "trace_id": mission.get("trace_id"),
            "agent_id": "bars",
            "status": status,
            "summary": summary,
            "artifacts": [],
            "evidence": [{"type": "trace", "ref": f"trace://{mission.get('trace_id', 'unknown')}"}],
            "failures": [],
            "human_blocker": None,
            "handoff": None,
            "memory_candidate": None,
            "next_action": None,
            "completed_at": None,
        }
        payload.update(extra)
        self._json(payload, code)

    def _invoke_engineering(self, mission):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not CONTROL_URL or len(os.environ.get("PAULI_CONTROL_TOKEN", "")) < 32:
            self._envelope(mission, "failed", "BARS engineering bridge is not configured.", 503,
                           failures=["Set PAULI_CONTROL_URL and PAULI_CONTROL_TOKEN on the BARS adapter."],
                           next_action="Configure engineering/pauli-control, then retry through Terabithia.",
                           completed_at=now)
            return
        try:
            request = _engineering_request(mission)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        try:
            started = _control("/run", "POST", request, timeout=30)
            job_id = str(started.get("jobId") or "")
            if not job_id:
                raise RuntimeError(started.get("error") or "engineering bridge did not return a job id")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read() or b"{}").get("error", "")
            except Exception:
                pass
            self._envelope(mission, "failed", "BARS engineering bridge refused the job.", 502,
                           failures=[f"HTTP {exc.code}: {detail}"[:500]], completed_at=now)
            return
        except Exception as exc:
            self._envelope(mission, "failed", "BARS engineering dispatch failed.", 502,
                           failures=[str(exc)[:500]], completed_at=now)
            return
        receipt = ENG_PREFIX + job_id
        self._envelope(mission, "working",
                       f"BARS started engineering job {job_id} in {request['mode']} mode on {started.get('repoPath') or request['repo']}.",
                       202,
                       evidence=[
                           {"type": "external_state", "ref": f"bars://engineering/{job_id}", "summary": "pauli-control job receipt"},
                           {"type": "trace", "ref": f"trace://{mission['trace_id']}"},
                       ],
                       next_action=f"Poll /api/terabithia/status/{receipt} for completion evidence.",
                       runtime={"bars_mission_id": receipt, "engineering_job_id": job_id, "mode": request["mode"]})

    def _engineering_status(self, receipt):
        job_id = receipt[len(ENG_PREFIX):]
        if not CONTROL_URL:
            self._json({"error": "engineering bridge not configured"}, 503)
            return
        try:
            job = _control(f"/runs/{job_id}", timeout=10)
        except urllib.error.HTTPError as exc:
            self._json({"error": f"engineering bridge returned HTTP {exc.code}"}, 404 if exc.code == 404 else 502)
            return
        except Exception as exc:
            self._json({"error": str(exc)[:300]}, 502)
            return
        raw = str(job.get("status") or "")
        mapped = {"running": "working", "success": "done", "error": "failed", "timeout": "failed"}.get(raw, "working")
        output = str(job.get("stdout") or "").strip()
        errors = str(job.get("stderr") or "").strip()
        evidence = [{"type": "external_state", "ref": f"bars://engineering/{job_id}", "summary": raw or "pauli-control state"}]
        if output:
            evidence.append({"type": "artifact", "ref": f"bars://engineering/{job_id}/stdout", "summary": output[-500:]})
        self._json({
            "bars_mission_id": receipt,
            "status": mapped,
            "raw_status": raw,
            "summary": output[-2000:] or f"Engineering job {job_id} is {raw or 'in progress'}.",
            "evidence": evidence,
            "failures": [errors[-500:] or f"job ended with status {raw}"] if mapped == "failed" else [],
            "completed_at": job.get("finishedAt") if mapped in {"done", "failed"} else None,
        })


if __name__ == "__main__":
    print(f"[BARS/Terabithia] adapter listening on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
