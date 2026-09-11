# BARS adversarial suite v3 - fourth-review findings. Versioned: adv-v3-<n>.
import json, os, shutil, subprocess, sys, threading, time
import urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bars_security as sec

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# adv-v3-1: budget fails CLOSED on corrupt state
BD = "/tmp/v3-budget"; shutil.rmtree(BD, ignore_errors=True); os.makedirs(BD)
open(os.path.join(BD, "budget.json"), "w").write("{corrupt json")
b = sec.BudgetLedger(os.path.join(BD, "budget.json"), 1000)
try:
    b.reserve(10, "x"); check("adv-v3-1 corrupt budget state fails closed", False)
except RuntimeError as e:
    check("adv-v3-1 corrupt budget state fails closed", "unreadable" in str(e), str(e)[:70])

# adv-v3-2: paid failure settles at estimate (conservative billable accounting)
shutil.rmtree(BD); os.makedirs(BD)
b = sec.BudgetLedger(os.path.join(BD, "budget.json"), 1000)
b.reserve(200, "h1"); b.fail("h1")
check("adv-v3-2 failed paid attempt settles at estimate", b.used() == 200, str(b.used()))

# adv-v3-3: stale holds surfaced + swept
b2 = sec.BudgetLedger(os.path.join(BD, "budget.json"), 1000)
b2.reserve(100, "fresh")
st = json.load(open(os.path.join(BD, "budget.json")))
st["holds"]["old"] = [50, time.time() - 9999]
json.dump(st, open(os.path.join(BD, "budget.json"), "w"))
check("adv-v3-3a stale hold surfaced", "old" in b2.stale_holds(), str(b2.stale_holds()))
swept = b2.sweep_stale()
check("adv-v3-3b stale hold swept, fresh kept", "old" in swept and "fresh" in json.load(open(os.path.join(BD, "budget.json")))["holds"])

# adv-v3-4: confirmation recipient enforcement + cost/expiry metadata
cs = sec.ConfirmationStore()
o = cs.mint("chat.exec", {"text": "hi"}, "/chat")
check("adv-v3-4a mint carries cost bound", o.get("cost_bound") == 4096 and o.get("ttl_seconds") is None and "expires_at" in o, str(o)[:120])
try:
    cs.consume(o["id"], "chat.exec", {"text": "hi"}, recipient="/see")
    check("adv-v3-4b recipient mismatch refused", False)
except RuntimeError as e:
    check("adv-v3-4b recipient mismatch refused", "recipient" in str(e), str(e)[:60])

# adv-v3-5: receipt anchor written; tampered anchor surfaced at startup
RD = "/tmp/v3-rec"; shutil.rmtree(RD, ignore_errors=True); os.makedirs(RD)
r = sec.ReceiptLedger(os.path.join(RD, "receipts.jsonl"), os.path.join(RD, ".k"))
r.append({"kind": "chat", "i": 1})
check("adv-v3-5a anchor file written", os.path.exists(os.path.join(RD, "receipts.jsonl.anchor")))
a = json.load(open(os.path.join(RD, "receipts.jsonl.anchor")))
a["seq"] = 999
json.dump(a, open(os.path.join(RD, "receipts.jsonl.anchor"), "w"))
r2 = sec.ReceiptLedger(os.path.join(RD, "receipts.jsonl"), os.path.join(RD, ".k"))
findings = r2.status().get("startup_findings", [])
check("adv-v3-5b anchor tamper surfaced at startup/status", any("anchor" in f for f in findings), str(findings)[:120])

# adv-v3-6: key-host binding guard (static path refuses foreign host)
src = open(os.path.join(ROOT, "server.py")).read()
check("adv-v3-6a key-host binding enforced in chat path", "key-host binding: refusing" in src)
check("adv-v3-6b model switch refuses foreign host", "model switch refused" in src)

# adv-v3-7: hands_go body fallback removed; exact task bound
hsrc = open(os.path.join(ROOT, "hands.py")).read()
check("adv-v3-7a hands_go body fallback removed", 'or (p.get("task")' not in hsrc)
check("adv-v3-7b hands_go requires hands.exec confirmation", 'hands.exec' in hsrc)

# adv-v3-8: authority-laundering claim gone from prompts
check("adv-v3-8 authority claim removed from prompts", "has explicitly confirmed this action" not in src)

# adv-v3-9: login lockout (5 failures -> 429), XFF-aware
DATA = "/tmp/v3-data"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="v3tok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app", GROQ_API_TOKEN="fake",
           BARS_BASE_URL="http://127.0.0.1:9999/v1", BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4333")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_v3.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4333"
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

codes = []
for i in range(6):
    s, _, _ = req("POST", "/api/session", {"token": "wrong"},
                  {"X-Forwarded-For": "203.0.113.7"})
    codes.append(s)
check("adv-v3-9 login lockout after 5 failures (XFF honored)", codes[-1] == 429, str(codes))

# adv-v3-10: UX policy - ordinary chat needs NO approval (conversational inference)
TOK = {"Authorization": "Bearer v3tok"}
s, h, b = req("POST", "/chat", {"text": "hello there"}, TOK)
check("adv-v3-10 chat ungated by policy", s == 200 and b.get("reply"), str(b.get("reply"))[:60])
# a REAL follow-up MISSION still needs its own confirmation (proven live in
# adv-v9-9b: 409 displays the 8192 bound). Updated 14th round: the existence
# check now runs BEFORE confirmation consumption, so a dead follow-up 400s
# without burning a single-use approval (adv-v9-13 proves no burn).
s, h, b = req("POST", "/followup", {"mission": "m1"}, TOK)
check("adv-v3-10b dead followup 400s pre-confirmation; live gating proven in adv-v9-9b/v9-13",
      s == 400 and "no follow-up" in str(b.get("error", "")), f"{s} {b}")

s, h, b = req("POST", "/chat", {"text": "hello there"}, TOK)
check("adv-v3-11 chat executes without confirmation", s == 200 and b.get("reply"), str(b.get("reply"))[:60])

# adv-v3-12: plan dry-run: squad uses mission.plan; non-squad plan never executes
s, h, b = req("POST", "/brief", {"brief": "squad: research y", "plan": True}, TOK)
check("adv-v3-12 squad plan uses mission.plan action", s == 409 and b.get("need_confirmation", {}).get("action") == "mission.plan", str(b.get("need_confirmation")))
s, h, b = req("POST", "/brief", {"brief": "research y solo", "plan": True}, TOK)
check("adv-v3-12b non-squad plan is 400, never executes", s == 400 and "only meaningful for squad" in str(b.get("error","")), str(b))

# adv-v3-13: mission id validation
s, h, b = req("GET", "/mission/zzzz", headers=TOK)
check("adv-v3-13a bad mission id 400", s == 400)
s, h, b = req("GET", "/mission/..%2f..%2fetc", headers=TOK)
check("adv-v3-13b traversal mission id 400", s == 400)

# adv-v3-14: abort stops internal worker and stays ABORTED
s, h, cj = req("POST", "/api/confirmations", {"action": "mission.exec", "payload": {"brief": "research abort semantics deeply"}, "recipient": "/brief"}, TOK)
H = dict(TOK); H["X-BARS-Confirmation"] = cj.get("id", "")
s, h, b = req("POST", "/brief", {"brief": "research abort semantics deeply"}, H)
mid = b.get("id")
s, h, b = req("POST", "/abort", {"id": mid}, TOK)
time.sleep(3)
s, h, b = req("GET", f"/mission/{mid}", headers=TOK)
check("adv-v3-14 abort stops internal worker", b.get("status") == "ABORTED", str(b.get("status")))

srv.terminate(); srv.wait(5); mock.terminate()
print(f"\n== {len(passed)} passed, {len(failed)} failed ==")
if failed: print("FAILED:", failed); sys.exit(1)
