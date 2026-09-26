# Terabithia adapter contract: BARS accepts operator + engineering routes (Pi split, 2026-09-26)
# and enforces BARS_TERABITHIA_TOKEN when it is set. Engineering missions go to the
# engineering/pauli-control bridge (fake here) and are refused, never faked, when it is not configured. Run: python3 tests/test_terabithia_adapter.py
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

CONTROL_TOKEN = "c" * 40
control_calls = []
class FakeControl(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        control_calls.append((self.path, self.headers.get("Authorization"), body))
        self._send(200, {"jobId": "11111111-2222-4333-8444-555555555555", "status": "running", "repoPath": "/w/repo"})
    def do_GET(self):
        control_calls.append((self.path, self.headers.get("Authorization"), None))
        self._send(200, {"status": "success", "stdout": "patched 2 files; tests pass", "stderr": "", "finishedAt": "2026-09-26T07:00:00Z"})

RENDER_TOKEN = "v" * 40
render_calls = []
class FakeRender(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        render_calls.append((self.path, self.headers.get("Authorization"), body))
        self._send(202, {"jobId": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "status": "linting"})
    def do_GET(self):
        render_calls.append((self.path, self.headers.get("Authorization"), None))
        self._send(200, {"status": "success", "finishedAt": "2026-09-26T11:00:00Z",
                         "artifact": {"path": "/w/launch/renders/x.mp4", "bytes": 454381, "sha256": "d" * 64}})

render = ThreadingHTTPServer(("127.0.0.1", 0), FakeRender)
threading.Thread(target=render.serve_forever, daemon=True).start()
os.environ["HYPERFRAMES_RENDER_URL"] = f"http://127.0.0.1:{render.server_address[1]}"
os.environ["HYPERFRAMES_RENDER_TOKEN"] = RENDER_TOKEN

fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeBars)
threading.Thread(target=fake.serve_forever, daemon=True).start()
control = ThreadingHTTPServer(("127.0.0.1", 0), FakeControl)
threading.Thread(target=control.serve_forever, daemon=True).start()
os.environ["BARS_LOCAL_URL"] = f"http://127.0.0.1:{fake.server_address[1]}"
os.environ["PAULI_CONTROL_URL"] = f"http://127.0.0.1:{control.server_address[1]}"
os.environ["PAULI_CONTROL_TOKEN"] = CONTROL_TOKEN
os.environ["BARS_TERABITHIA_TOKEN"] = "bars-test-token-0123456789"

import terabithia_adapter as ta
srv = ThreadingHTTPServer(("127.0.0.1", 0), ta.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

def invoke(route, token="bars-test-token-0123456789", **extra):
    body = {"mission_id": "a", "request_id": "b", "conversation_id": "c", "trace_id": "d",
            "target": "bars", "route": route, "user_intent": "fix the failing test", **extra}
    headers = {"Content-Type": "application/json"}
    if token is not None: headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + "/api/terabithia/invoke", data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")

def status(mid, token="bars-test-token-0123456789"):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    req = urllib.request.Request(base + f"/api/terabithia/status/{mid}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")

s, b = invoke("engineering", repo="repo")
receipt = (b.get("runtime") or {}).get("bars_mission_id", "")
check("engineering route dispatched to the engineering bridge", s == 202 and receipt.startswith("eng-"), f"{s} {receipt}")
path_, auth, body = control_calls[-1]
check("bridge got /run with its own bearer, plan mode, requested repo",
      path_ == "/run" and auth == f"Bearer {CONTROL_TOKEN}" and body == {"task": "fix the failing test", "mode": "plan", "repo": "repo"}, str(control_calls[-1]))
s, st = status(receipt)
check("engineering status maps bridge success to done with evidence", s == 200 and st.get("status") == "done" and "tests pass" in st.get("summary", ""), f"{s} {st.get('status')}")
s, _ = status(receipt, token=None); check("status without token refused", s == 401, f"{s}")
s, _ = invoke("engineering", mode="deploy-everything"); check("unknown engineering mode refused", s == 400, f"{s}")
saved, ta.CONTROL_URL = ta.CONTROL_URL, ""
calls_before = len(control_calls)
s, b = invoke("engineering"); check("unconfigured bridge: refused 503, nothing faked", s == 503 and b.get("status") == "failed" and len(control_calls) == calls_before, f"{s}")
ta.CONTROL_URL = saved
s, _ = invoke(["engineering"]); check("non-string route is a 409, not a 500", s == 409, f"{s}")

# video.render on the operator route goes to the HyperFrames render service, not the /brief mission path
s, b = invoke("operator", capability="video.render", render={"project": "launch", "quality": "draft", "evil": "x"})
vid = (b.get("runtime") or {}).get("bars_mission_id", "")
check("video.render dispatched to the render service", s == 202 and vid.startswith("vid-"), f"{s} {vid}")
path_, auth, body = render_calls[-1]
check("render service got its own bearer, only known fields, and the mission id as idempotency key",
      path_ == "/render" and auth == f"Bearer {RENDER_TOKEN}"
      and body == {"project": "launch", "quality": "draft", "idempotencyKey": "tb:a"}, str(render_calls[-1]))
s, st = status(vid)
path_, auth, body = render_calls[-1]
check("render status polls /renders/{jobId} with the render bearer",
      path_ == f"/renders/{vid[len('vid-'):]}" and auth == f"Bearer {RENDER_TOKEN}" and body is None, str(render_calls[-1]))
check("render status done carries the artifact hash as evidence",
      s == 200 and st.get("status") == "done" and any("sha256 " + "d" * 64 in e.get("summary", "") for e in st.get("evidence", [])), f"{s} {st.get('status')}")
s, _ = invoke("operator", capability="video.render"); check("video.render without a project refused", s == 400, f"{s}")
saved, ta.RENDER_URL = ta.RENDER_URL, ""
before_calls = len(render_calls)
s, b = invoke("operator", capability="video.render", render={"project": "launch"})
check("unconfigured video engine: 503, nothing faked", s == 503 and b.get("status") == "failed" and len(render_calls) == before_calls, f"{s}")
ta.RENDER_URL = saved
before_calls = len(render_calls)
s, _ = invoke("operator"); check("plain operator mission still goes to BARS, not the render service", s == 202 and len(render_calls) == before_calls, f"{s}")
s, _ = invoke("operator"); check("operator route still accepted", s == 202, f"{s}")
s, _ = invoke("personal"); check("personal route refused", s == 409, f"{s}")
s, _ = invoke("engineering", token=None); check("missing token refused", s == 401, f"{s}")
s, _ = invoke("engineering", token="x" * 400); check("wrong/oversized token refused", s == 401, f"{s}")

# The public capability list must not call the video engine usable unless the render service is configured.
import subprocess
_caps_js = ("import('./lib/bars-capabilities.js').then(m => { const v = e => m.publicCapabilityStatus(e).find(c => c.id === 'hyperframes-video').status;"
            " console.log(JSON.stringify([v({ HERMES_REMOTE_URL: 'h', HERMES_API_KEY: 'k' }), v({ HYPERFRAMES_RENDER_URL: 'http://127.0.0.1:8788', HYPERFRAMES_RENDER_TOKEN: 'x'.repeat(40) })])); })")
_caps = subprocess.run(["node", "-e", _caps_js], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), capture_output=True, text=True)
check("hyperframes-video is 'declared' without the render service, 'configured' with it",
      _caps.stdout.strip() == '["declared","configured"]', _caps.stdout + _caps.stderr)

print(f"\n{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
