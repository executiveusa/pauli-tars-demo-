# BARS sovereign security assertions v1 (review hardening). Each check is
# versioned: sec-v1-<n>. Run: python3 test_security.py
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bars_security as sec

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# --- sec-v1-1..4: origin allowlist parsing (unit)
try:
    sec.parse_origin_allowlist("https://*.example.com"); check("sec-v1-1 wildcard rejected", False)
except sec.SecurityConfigError: check("sec-v1-1 wildcard rejected", True)
try:
    sec.parse_origin_allowlist("https://a.example.com/path"); check("sec-v1-2 path rejected", False)
except sec.SecurityConfigError: check("sec-v1-2 path rejected", True)
try:
    sec.parse_origin_allowlist("http://remote.example.com"); check("sec-v1-3 remote http rejected", False)
except sec.SecurityConfigError: check("sec-v1-3 remote http rejected", True)
t = sec.parse_origin_allowlist("https://barsdemo.netlify.app,http://localhost:3000")
check("sec-v1-4 exact parse", ("https","barsdemo.netlify.app",None) in t and ("http","localhost",3000) in t, str(t))
check("sec-v1-5 exact host match", sec.origin_allowed("https://barsdemo.netlify.app", t) and not sec.origin_allowed("https://barsdemo.netlify.app.evil.com", t) and not sec.origin_allowed("https://sub.barsdemo.netlify.app", t))
check("sec-v1-6 empty origin allowed (same-origin model)", sec.origin_allowed("", t))
check("sec-v1-7 wrong scheme refused", not sec.origin_allowed("http://barsdemo.netlify.app", t, allow_local_dev=False))

# --- sec-v1-8..12: budget ledger atomicity (unit)
BL = "/tmp/sec-budget"; shutil.rmtree(BL, ignore_errors=True); os.makedirs(BL)
b = sec.BudgetLedger(os.path.join(BL, "budget.json"), 1000)
b.reserve(400, "h1"); b.reserve(400, "h2")
try:
    b.reserve(400, "h3"); check("sec-v1-8 over-budget reserve refused", False)
except RuntimeError: check("sec-v1-8 over-budget reserve refused", True)
b.settle("h1", 390); check("sec-v1-9 settle counts actuals", b.used() == 390, str(b.used()))
b.release("h2"); b.reserve(600, "h4"); check("sec-v1-10 release frees budget", True)
check("sec-v1-11 ledger durable on disk", os.path.exists(os.path.join(BL, "budget.json")))
st = os.stat(os.path.join(BL, "budget.json")); check("sec-v1-12 budget file 0600", (st.st_mode & 0o777) == 0o600, oct(st.st_mode & 0o777))

# --- sec-v1-13..16: receipt ledger integrity (unit)
RL = os.path.join(BL, "receipts.jsonl")
r = sec.ReceiptLedger(RL, os.path.join(BL, ".k"))
for i in range(3): r.append({"kind": "chat", "i": i})
c, bad = r.verify(); check("sec-v1-13 hmac chain verifies", c == 3 and bad == 0, f"{c}/{bad}")
lines = open(RL).read().splitlines()
ev = json.loads(lines[1]); ev["i"] = 999
lines[1] = json.dumps(ev)
open(RL, "w").write("\n".join(lines) + "\n")
r2 = sec.ReceiptLedger(RL, os.path.join(BL, ".k"))
c, bad = r2.verify(); check("sec-v1-14 tamper detected", bad >= 1, f"bad={bad}")
check("sec-v1-15 write failures surfaced", r2.status()["write_failures"] == 0 and "integrity" in r2.status())
r3 = sec.ReceiptLedger(RL, os.path.join(BL, ".k")); r3.MAX_BYTES = 10
r3.append({"kind": "rotate"}); check("sec-v1-16 rotation renames", os.path.exists(RL + ".1"))

# --- sec-v1-17..21: confirmations (unit)
cs = sec.ConfirmationStore()
o = cs.mint("mission.exec", {"brief": "x"}, "/brief")
check("sec-v1-17 mint binds fields", all(k in o for k in ("id", "payload_sha256", "recipient", "expires_at", "nonce")))
try:
    cs.consume(o["id"], "mission.exec", {"brief": "y"}); check("sec-v1-18 payload swap refused", False)
except RuntimeError: check("sec-v1-18 payload swap refused", True)
cs.consume(cs.mint("mission.exec", {"brief": "x"}, "/brief")["id"], "mission.exec", {"brief": "x"})
check("sec-v1-19 exact payload accepted", True)
try:
    cs.consume(o["id"], "mission.exec", {"brief": "x"}); check("sec-v1-20 single-use", False)
except RuntimeError: check("sec-v1-20 single-use", True)
try:
    cs.mint("no.such.action", {}, "x"); check("sec-v1-21 unknown action refused", False)
except sec.SecurityConfigError: check("sec-v1-21 unknown action refused", True)

# --- sec-v1-22: fail-closed startup without operator token
env = dict(os.environ); env.pop("BARS_OPERATOR_TOKEN", None); env.pop("BARS_OPEN_LOCAL", None)
p = subprocess.run([sys.executable, "server.py"], cwd=ROOT, env=env,
                   capture_output=True, text=True, timeout=10)
check("sec-v1-22 startup fail-closed without token", p.returncode != 0 and "FATAL" in (p.stderr + p.stdout), (p.stderr + p.stdout).strip()[:80])

# --- sec-v1-23: invalid allowlist entry aborts startup
env["BARS_OPERATOR_TOKEN"] = "x"; env["BARS_ALLOWED_ORIGINS"] = "not-a-url"
p = subprocess.run([sys.executable, "server.py"], cwd=ROOT, env=env,
                   capture_output=True, text=True, timeout=10)
check("sec-v1-23 startup fail-closed bad origin", p.returncode != 0 and "FATAL" in (p.stderr + p.stdout))

# --- sec-v1-24..28: live server: CSRF, duplex perms, builds sandbox
DATA = "/tmp/secdata"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="sectok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app", GROQ_API_TOKEN="fake",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1", BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4327")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_sec.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4327"
def req(method, path, body=None, headers=None, raw=False):
    h = dict(headers or {}); data = None
    if body is not None: data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            b = resp.read()
            return resp.status, dict(resp.headers), (b if raw else json.loads(b or b"{}"))
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, dict(e.headers), json.loads(b or b"{}")
        except Exception: return e.code, dict(e.headers), {"raw": b[:200].decode(errors="replace")}
for _ in range(40):
    try: req("GET", "/health"); break
    except Exception: time.sleep(0.25)

s, h, sess = req("POST", "/api/session", {"token": "sectok"})
ck = (h.get("Set-Cookie") or "")
sid = [p for p in ck.split(";") if p.startswith("bars_session=")][0]
s, h, b = req("POST", "/remember", {"text": "x"}, headers={"Cookie": sid})
check("sec-v1-24 session mutation without csrf refused", s == 401, str(s))
s, h, b = req("GET", "/api/session", headers={"Cookie": sid})
csrf = b.get("csrf", "")
s, h, b = req("POST", "/remember", {"text": "x"}, headers={"Cookie": sid, "X-CSRF-Token": csrf})
check("sec-v1-25 session mutation with csrf ok", s == 200 and b.get("ok"), str(b)[:60])
s, h, b = req("POST", "/remember", {"text": "x"}, headers={"Cookie": sid, "X-CSRF-Token": "wrong"})
check("sec-v1-26 wrong csrf refused", s == 401)
st = os.stat(os.path.join(DATA, "bars-duplex.json"))
check("sec-v1-27 duplex token file 0600", (st.st_mode & 0o777) == 0o600, oct(st.st_mode & 0o777))
os.makedirs(os.path.join(DATA, "builds", "demo"), exist_ok=True)
open(os.path.join(DATA, "builds", "demo", "index.html"), "w").write("<h1>demo</h1>")
s, h, b = req("GET", "/builds/demo/", headers={"Authorization": "Bearer sectok"}, raw=True)
check("sec-v1-28 builds served with CSP sandbox", s == 200 and "sandbox" in (h.get("Content-Security-Policy") or ""), h.get("Content-Security-Policy"))

srv.terminate(); srv.wait(5); mock.terminate()
print(f"\n== {len(passed)} passed, {len(failed)} failed ==")
if failed: print("FAILED:", failed); sys.exit(1)
