# Terabithia adapter contract: BARS accepts operator + engineering routes (Pi split, 2026-09-26)
# and enforces BARS_TERABITHIA_TOKEN when it is set. Run: python3 tests/test_terabithia_adapter.py
import json, os, sys, threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

class FakeBars(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        raw = json.dumps({"id": "m-1"}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeBars)
threading.Thread(target=fake.serve_forever, daemon=True).start()
os.environ["BARS_LOCAL_URL"] = f"http://127.0.0.1:{fake.server_address[1]}"
os.environ["BARS_TERABITHIA_TOKEN"] = "bars-test-token-0123456789"

import terabithia_adapter as ta
srv = ThreadingHTTPServer(("127.0.0.1", 0), ta.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

def invoke(route, token="bars-test-token-0123456789"):
    body = {"mission_id": "a", "request_id": "b", "conversation_id": "c", "trace_id": "d",
            "target": "bars", "route": route, "user_intent": "fix the failing test"}
    headers = {"Content-Type": "application/json"}
    if token is not None: headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + "/api/terabithia/invoke", data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")

s, b = invoke("engineering"); check("engineering route accepted", s == 202 and b.get("agent_id") == "bars", f"{s}")
s, _ = invoke("operator"); check("operator route still accepted", s == 202, f"{s}")
s, _ = invoke("personal"); check("personal route refused", s == 409, f"{s}")
s, _ = invoke("engineering", token=None); check("missing token refused", s == 401, f"{s}")
s, _ = invoke("engineering", token="x" * 400); check("wrong/oversized token refused", s == 401, f"{s}")

print(f"\n{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
