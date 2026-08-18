#!/usr/bin/env python3
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REMOTE_REPORTS = []
CLAIMED = False


class RemoteHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def _json(self, code, payload=None):
        raw = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(code)
        if raw:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw: self.wfile.write(raw)
    def do_POST(self):
        global CLAIMED
        if self.headers.get("Authorization") != "Bearer test-token":
            return self._json(401, {"error": "Unauthorized"})
        if self.path == "/api/v1/operators/bars/claim":
            if CLAIMED: return self._json(204)
            CLAIMED = True
            return self._json(200, {
                "mission_id": "bars_test_1",
                "request_id": "req_1",
                "conversation_id": "conv_1",
                "trace_id": "trace_1",
                "user_intent": "Inspect the demo page and return evidence.",
                "status": "claimed",
            })
        if self.path == "/api/v1/operators/bars/report":
            n = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            REMOTE_REPORTS.append(payload)
            return self._json(200, payload)
        return self._json(404, {"error": "NotFound"})


class LocalBarsHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if self.path == "/brief":
            return self._json(200, {"id": "local_123"})
        return self._json(404, {})
    def do_GET(self):
        if self.path == "/mission/local_123":
            return self._json(200, {"status": "DONE", "debrief": "Demo inspection completed with evidence."})
        return self._json(404, {})


def start(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    remote = start(RemoteHandler); local = start(LocalBarsHandler)
    os.environ["TERABITHIA_REMOTE_URL"] = f"http://127.0.0.1:{remote.server_port}"
    os.environ["TERABITHIA_API_KEY"] = "test-token"
    os.environ["BARS_LOCAL_URL"] = f"http://127.0.0.1:{local.server_port}"
    os.environ["BARS_NODE_ID"] = "ci-node"
    os.environ["BARS_REMOTE_POLL_SECONDS"] = "0.01"
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import remote_bridge
    remote_bridge.POLL_SECONDS = 0.01
    try:
        assert remote_bridge.run_once() is True
        assert len(REMOTE_REPORTS) >= 2, REMOTE_REPORTS
        assert REMOTE_REPORTS[0]["status"] == "working", REMOTE_REPORTS
        final = REMOTE_REPORTS[-1]
        assert final["status"] == "done", final
        assert final["bars_mission_id"] == "local_123", final
        assert final["evidence"], final
        print("REMOTE_MISSION_PROOF_OK")
    finally:
        remote.shutdown(); local.shutdown()


if __name__ == "__main__":
    main()
