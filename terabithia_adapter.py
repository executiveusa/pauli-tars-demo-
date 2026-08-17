#!/usr/bin/env python3
"""Terabithia adapter sidecar for BARS.

Keeps the existing BARS cockpit/server untouched while exposing a narrow,
standard fleet contract on port 4324.
"""
import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BARS_URL = os.environ.get("BARS_LOCAL_URL", "http://127.0.0.1:4321").rstrip("/")
PORT = int(os.environ.get("BARS_TERABITHIA_PORT", "4324"))


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
        if self.path.rstrip("/") != "/health":
            self._json({"error": "not found"}, 404)
            return
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

    def do_POST(self):
        if self.path.rstrip("/") != "/api/terabithia/invoke":
            self._json({"error": "not found"}, 404)
            return

        mission = self._body()
        required = ("mission_id", "request_id", "conversation_id", "trace_id", "target", "route", "user_intent")
        missing = [key for key in required if not str(mission.get(key, "")).strip()]
        if missing:
            self._json({"error": "missing required mission fields", "fields": missing}, 400)
            return
        if mission.get("target") != "bars" or mission.get("route") != "operator":
            self._json({"error": "BARS only accepts operator missions targeted to bars"}, 409)
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
                "summary": f"BARS accepted the operator mission as {bars_mission_id}.",
                "artifacts": [],
                "evidence": [
                    {"type": "external_state", "ref": f"bars://mission/{bars_mission_id}", "summary": "BARS mission receipt"},
                    {"type": "trace", "ref": f"trace://{mission['trace_id']}"},
                ],
                "failures": [],
                "human_blocker": None,
                "handoff": None,
                "memory_candidate": None,
                "next_action": f"Poll BARS mission {bars_mission_id} for completion evidence.",
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


if __name__ == "__main__":
    print(f"[BARS/Terabithia] adapter listening on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
