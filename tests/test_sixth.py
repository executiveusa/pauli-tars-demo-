# BARS adversarial suite v5 - sixth-review items. Versioned: adv-v5-<n>.
import json, os, shutil, subprocess, sys, threading, time
import urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bars_security as sec

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

DATA = "/tmp/v5-data"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="v5tok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app", GROQ_API_TOKEN="fake",
           BARS_BASE_URL="http://127.0.0.1:9999/v1", BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4336")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_v5.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4336"
TOK = {"Authorization": "Bearer v5tok"}
def req(method, path, body=None, headers=None):
    h = dict(headers or {}); data = None
    if body is not None: data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, dict(e.headers), json.loads(e.read() or b"{}")
        except Exception: return e.code, dict(e.headers), {}
for _ in range(40):
    try: req("GET", "/health"); break
    except Exception: time.sleep(0.25)
def mint(action, payload, recipient):
    s, h, cj = req("POST", "/api/confirmations", {"action": action, "payload": payload, "recipient": recipient}, TOK)
    assert s == 200 and cj.get("id"), f"mint failed {s} {cj}"
    h2 = dict(TOK); h2["X-BARS-Confirmation"] = cj["id"]
    return h2

TOOLS_FILE = os.path.join(DATA, "bars-tools.json")
def installed_tools():
    try: return (json.load(open(TOOLS_FILE)) or {}).get("installed", {})
    except Exception: return {}

# adv-v5-1: chat TOOL_ADD proposes only; /tools mutation needs exact tools.write confirmation
baseline = installed_tools()
s, h, b = req("POST", "/chat", {"text": "MOCKSAY one moment\n[TOOL_ADD: sentry]"}, TOK)
check("adv-v5-1a chat proposes tool add, no mutation",
      s == 200 and (b.get("tool") or {}).get("proposed") is True and b["tool"]["op"] == "add"
      and installed_tools() == baseline, f"{s} {b.get('tool')} {installed_tools()}")
s, h, b = req("POST", "/tools", {"op": "install", "id": "sentry"}, TOK)
check("adv-v5-1b install without confirmation 409", s == 409 and b.get("need_confirmation", {}).get("action") == "tools.write", str(s))
s, h, b = req("POST", "/tools", {"op": "install", "id": "sentry"}, mint("tools.write", {"op": "install", "id": "sentry"}, "/tools"))
check("adv-v5-1c install with exact confirmation works", s == 200 and "sentry" in installed_tools(), f"{s} {str(b)[:160]}")
s, h, b = req("POST", "/tools", {"op": "remove", "id": "sentry"}, TOK)
check("adv-v5-1d removal gated the same way (409)", s == 409, str(s))
s, h, b = req("POST", "/tools", {"op": "remove", "id": "sentry"}, mint("tools.write", {"op": "install", "id": "sentry"}, "/tools"))
check("adv-v5-1e install payload cannot authorize removal", s == 409 and "sentry" in installed_tools(), str(s))
s, h, b = req("POST", "/tools", {"op": "remove", "id": "sentry"}, mint("tools.write", {"op": "remove", "id": "sentry"}, "/tools"))
check("adv-v5-1f removal with exact confirmation works", s == 200 and "sentry" not in installed_tools(), str(s))

# adv-v5-2: /see DEPLOY proposes only; no mission started
s, h, b = req("POST", "/see", {"image": "data:image/png;base64,iVBORw0KGgo=",
                               "question": "MOCKSAY nice screen\n[DEPLOY: research competitor onboarding flows]"}, TOK)
check("adv-v5-2a see proposes mission only", s == 200 and (b.get("deployed") or {}).get("proposed") is True and not b["deployed"].get("id"), f"{s} {b.get('deployed')}")
s, h, b = req("GET", "/api/status", headers=TOK)
check("adv-v5-2b no mission was started", not b.get("missions"), str(b.get("missions"))[:80])

# adv-v5-3: ACT creates immutable action id; act.exec binds exact object, single-use
s, h, b = req("POST", "/chat", {"text": "MOCKSAY queued\n[ACT: post the announcement]"}, TOK)
aid = (b.get("pending") or {}).get("id")
check("adv-v5-3a chat returns server-generated action id", s == 200 and aid, str(b.get("pending")))
s, h, b = req("POST", "/act", {"action_id": aid}, TOK)
check("adv-v5-3b act without confirmation 409", s == 409 and b.get("need_confirmation", {}).get("action") == "act.exec", str(s))
s, h, b = req("POST", "/act", {"action_id": aid}, mint("act.exec", {"action_id": aid, "instruction": "different text"}, "/act"))
check("adv-v5-3c wrong-payload confirmation refused", s == 409, str(s))
req("POST", "/dials", {"trust": "confirm-to-act"}, TOK)
H = mint("act.exec", {"action_id": aid, "instruction": "post the announcement"}, "/act")
s, h, b = req("POST", "/act", {"action_id": aid}, H)
check("adv-v5-3d act executes by id with exact confirmation", s == 200 and b.get("id"), f"{s} {str(b)[:80]}")
s, h, b = req("POST", "/act", {"action_id": aid}, H)
check("adv-v5-3e action single-use (gone after execute)", s == 400, str(s))
s, h, b = req("POST", "/act", {}, TOK)
check("adv-v5-3f missing action id 400", s == 400, str(s))

# adv-v5-4: hands_go canonical binding (unit, fake handler)
import hands
class FakeH2:
    def __init__(self): self.out = None; self.gated = None
    def _json(self, obj, code=200): self.out = (code, obj)
    def _need_confirmation(self, action, payload, recipient=None):
        self.gated = (action, payload, recipient); return False
fh = FakeH2()
hands.PENDING.clear(); hands.PENDING["cid1"] = "fill the form"
hands.handle(fh, "POST", "/hands_go", {"confirm_id": "cid1", "task": "DIFFERENT task"})
check("adv-v5-4a mismatched body task refused + pending restored",
      fh.out and fh.out[0] == 400 and "mismatch" in fh.out[1].get("error", "")
      and hands.PENDING.get("cid1") == "fill the form", str(fh.out))
hands.handle(fh, "POST", "/hands_go", {"confirm_id": "cid1", "task": "fill the form"})
check("adv-v5-4b canonical object bound to confirmation",
      fh.gated == ("hands.exec", {"confirm_id": "cid1", "task": "fill the form"}, "/hands_go"), str(fh.gated))

# adv-v5-5: XFF rightmost-trusted chain walk (unit)
os.environ.update(BARS_OPERATOR_TOKEN="v5tok", BARS_DATA_DIR=os.path.join(DATA, "d2"),
                  BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1")
import importlib, server
importlib.reload(server)
class FakeIP:
    headers = {}
    client_address = ("127.0.0.1", 1)
    TRUSTED_PROXIES = frozenset({"127.0.0.1", "::1"})
f = FakeIP()
f.headers = {"X-Forwarded-For": "9.9.9.9, 203.0.113.5"}
check("adv-v5-5a rightmost untrusted hop wins (spoofed left ignored)",
      server.Handler._client_ip(f) == "203.0.113.5", server.Handler._client_ip(f))
f.headers = {"X-Forwarded-For": "203.0.113.5, 127.0.0.1"}
check("adv-v5-5b trusted hops skipped", server.Handler._client_ip(f) == "203.0.113.5")
f.client_address = ("8.8.8.8", 1)
check("adv-v5-5c untrusted peer: XFF ignored entirely", server.Handler._client_ip(f) == "8.8.8.8")

# adv-v5-6: throttle state pruned (bounded)
fh3 = FakeIP(); fh3.LOGIN_FAILS = {f"10.0.0.{i}": {"n": 1, "t": time.time() - 9999} for i in range(100)}
fh3.LOGIN_LOCK = threading.Lock()
server.Handler._prune_throttle(fh3, time.time())
check("adv-v5-6 stale throttle records pruned", len(fh3.LOGIN_FAILS) == 0, str(len(fh3.LOGIN_FAILS)))

# adv-v5-7: receipt anchor vanishing at runtime -> fail-closed
RD = "/tmp/v5-rec"; shutil.rmtree(RD, ignore_errors=True); os.makedirs(RD)
led = os.path.join(RD, "receipts.jsonl")
r = sec.ReceiptLedger(led, os.path.join(RD, ".k"))
r.append({"kind": "a"}); r.append({"kind": "b"})
n_before = len(open(led).read().strip().splitlines())
os.remove(led + ".anchor")
r.append({"kind": "c"})
n_after = len(open(led).read().strip().splitlines())
check("adv-v5-7 runtime anchor vanish fail-closed, no append",
      r.write_failures > 0 and "disappeared" in str(r.last_error) and n_after == n_before,
      f"{r.last_error} lines {n_before}->{n_after}")

# adv-v5-8: abort ends ABORTED truthfully (live internal-worker mission)
H = mint("mission.exec", {"brief": "research abort semantics v5"}, "/brief")
s, h, b = req("POST", "/brief", {"brief": "research abort semantics v5"}, H)
mid = b.get("id")
s, h, b = req("POST", "/abort", {"id": mid}, TOK)
check("adv-v5-8a abort accepted", s == 200 and b.get("ok"), f"{s} {b}")
final = None
for _ in range(40):
    s, h, b = req("GET", f"/mission/{mid}", headers=TOK)
    final = (b.get("mission") or b).get("status")
    if final == "ABORTED": break
    time.sleep(0.25)
check("adv-v5-8b mission ends ABORTED truthfully", final == "ABORTED", str(final))

srv.terminate(); srv.wait(5); mock.terminate()

# adv-v5-9: rollback relinks current/previous for repeated rollback + verifies SHA
SB = "/tmp/v5-deploy"; shutil.rmtree(SB, ignore_errors=True)
os.makedirs(SB + "/bin"); os.makedirs(SB + "/root/app"); os.makedirs(SB + "/root/data"); os.makedirs(SB + "/root/backups")
for f in ("deploy.sh", "rollback.sh"):
    shutil.copy(os.path.join(ROOT, "deploy", f), SB + "/root/app/" + f)
shutil.copy(os.path.join(ROOT, "docker-compose.yml"), SB + "/root/app/docker-compose.yml")
stub = ('#!/bin/bash\necho "$(basename $0) $@" >> ' + SB + '/calls.log\n'
        'if [ "$(basename $0)" = "git" ] && [ "$1" = "rev-parse" ]; then echo "$BARS_FAKE_HEAD"; exit 0; fi\n'
        'if [ "$(basename $0)" = "curl" ]; then echo "{\\"sha\\": \\"$(cat $BARS_ROOT/current.sha 2>/dev/null)\\"}"; exit 0; fi\n'
        'exit 0\n')
for t in ("docker", "curl", "git", "tar", "mktemp", "mv"):
    open(SB + "/bin/" + t, "w").write(stub); os.chmod(SB + "/bin/" + t, 0o755)
A, Bv = "a" * 40, "b" * 40
def run(script, sha, head):
    e = dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root", BARS_FAKE_HEAD=head)
    return subprocess.run(["sh", SB + "/root/app/" + script] + ([sha] if sha else []),
                          env=e, capture_output=True, text=True)
p = run("deploy.sh", A, A); assert p.returncode == 0, p.stdout + p.stderr
p = run("deploy.sh", Bv, Bv); assert p.returncode == 0, p.stdout + p.stderr
p = run("rollback.sh", None, "")
check("adv-v5-9a rollback verifies + relinks (current=A, previous=B)",
      p.returncode == 0 and open(SB + "/root/current.sha").read().strip() == A
      and open(SB + "/root/previous.sha").read().strip() == Bv,
      f"rc={p.returncode} cur={open(SB + '/root/current.sha').read().strip()[:8]} err={p.stderr[-120:]}")
check("adv-v5-9c state tracked: rolled-back-from + snapshot links swap",
      open(SB + "/root/rolled-back-from.sha").read().strip() == Bv
      and open(SB + "/root/current.snapshot").read().strip().endswith(f"data-{A}.tar.gz")
      and open(SB + "/root/previous.snapshot").read().strip().endswith(f"data-{Bv}.tar.gz"),
      open(SB + "/root/rolled-back-from.sha").read().strip()[:8])
p = run("rollback.sh", None, "")
check("adv-v5-9b repeated rollback swaps back (current=B, previous=A)",
      p.returncode == 0 and open(SB + "/root/current.sha").read().strip() == Bv
      and open(SB + "/root/previous.sha").read().strip() == A,
      f"rc={p.returncode} err={p.stderr[-120:]}")

print(f"\n{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
