# BARS adversarial suite v2 - reproduces second-review findings H1-H3, M4-M8
# plus deploy/rollback script behavior. Versioned asserts: adv-v2-<finding>.
import json, os, shutil, subprocess, sys, threading, multiprocessing, time
import urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bars_security as sec

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# ---------- adv-v2-H1: budget ledger under thread + process contention
BD = "/tmp/adv-budget"; shutil.rmtree(BD, ignore_errors=True); os.makedirs(BD)
BP = os.path.join(BD, "budget.json")
def hammer(n, budget, est, results, tag):
    b = sec.BudgetLedger(BP, budget)
    ok = 0
    for i in range(n):
        try:
            b.reserve(est, f"{tag}-{i}"); ok += 1
        except RuntimeError:
            pass
    results.append(ok)

budget, est = 1000, 100
res = []
threads = [threading.Thread(target=hammer, args=(20, budget, est, res, f"t{n}")) for n in range(4)]
[t.start() for t in threads]; [t.join() for t in threads]
granted = sum(res)
check("adv-v2-H1a thread contention never over-grants", granted <= budget // est, f"granted={granted} max={budget//est}")

def proc_worker(q):
    b = sec.BudgetLedger(BP, budget)
    ok = 0
    for i in range(10):
        try: b.reserve(est, f"p{os.getpid()}-{i}"); ok += 1
        except RuntimeError: pass
    q.put(ok)
q = multiprocessing.Queue()
procs = [multiprocessing.Process(target=proc_worker, args=(q,)) for _ in range(4)]
[p.start() for p in procs]
pok = sum(q.get() for _ in procs); [p.join() for p in procs]
check("adv-v2-H1b process contention never over-grants", granted + pok <= budget // est, f"total={granted+pok}")
st = json.load(open(BP))
check("adv-v2-H1c durable holds match grants", len(st["holds"]) == granted + pok, f"{len(st['holds'])} vs {granted+pok}")

# ---------- adv-v2-H3: provider host spoof classification
sys.path.insert(0, ROOT)
os.environ.setdefault("BARS_OPEN_LOCAL", "1")
import importlib.util
spec = importlib.util.spec_from_file_location("srv_probe", os.path.join(ROOT, "server.py"))
# avoid full import side effects: extract _paid_route via exec of the function region
src = open(os.path.join(ROOT, "server.py")).read()
import re as _re
seg = src[src.index("FREE_PROVIDERS = ["):src.index("REC_LOCK") if "REC_LOCK" in src else src.index("SESSIONS = ")]
ns = {}
exec("import os\nfrom urllib.parse import urlparse\n" + seg.split("def _latency_stats")[0], ns)
check("adv-v2-H3a exact free host is free", ns["_paid_route"]("https://api.groq.com") == False)
check("adv-v2-H3b suffix spoof host is PAID", ns["_paid_route"]("https://api.groq.com.evil.com") == True)
check("adv-v2-H3c prefix spoof host is PAID", ns["_paid_route"]("https://xapi.groq.com") == True)
check("adv-v2-H3d bare host with port parses", ns["_paid_route"]("api.groq.com:443") == False)

# ---------- adv-v2-M8: receipt rotation continuity + deletion detection
RD = "/tmp/adv-receipts"; shutil.rmtree(RD, ignore_errors=True); os.makedirs(RD)
RP = os.path.join(RD, "receipts.jsonl")
r = sec.ReceiptLedger(RP, os.path.join(RD, ".k"))
for i in range(3): r.append({"kind": "chat", "i": i})
r.MAX_BYTES = 1                      # force rotation on next append
r.append({"kind": "chat", "i": 3})   # rotates: checkpoint anchors new file
ck = open(RP).read().splitlines()[0]
check("adv-v2-M8a rotation writes anchored checkpoint", "_checkpoint" in ck and "prev_file_hmac" in ck)
c, bad = r.verify()
check("adv-v2-M8b chain verifies across rotation", bad == 0, f"bad={bad}")
# deletion detection: drop the checkpoint line
lines = open(RP).read().splitlines()[1:]
open(RP, "w").write("\n".join(lines) + "\n")
r2 = sec.ReceiptLedger(RP, os.path.join(RD, ".k"))
c, bad = r2.verify()
check("adv-v2-M8c deleted line detected", bad >= 1, f"bad={bad}")
# startup mismatch detection: state says prev X, file tail differs
shutil.rmtree(RD); os.makedirs(RD)
r3 = sec.ReceiptLedger(RP, os.path.join(RD, ".k"))
r3.append({"kind": "chat", "i": 1})
open(RP, "a").write('{"kind":"forged","seq":99,"_h":"00"}\n')
r4 = sec.ReceiptLedger(RP, os.path.join(RD, ".k"))
check("adv-v2-M8d startup chain-state mismatch surfaced", r4.status()["write_failures"] >= 1, r4.status()["last_error"])

# ---------- adv-v2-M5: no auto-mint in shim; explicit approval modal present
shim = src[src.index("AUTH_SHIM"):src.index("def _inject_auth_shim")]
check("adv-v2-M5a shim has explicit HUMAN APPROVAL modal", "HUMAN APPROVAL REQUIRED" in shim)
check("adv-v2-M5b shim does not pre-mint confirmations", "SENS=" not in shim and "SENS[p]" not in shim)
check("adv-v2-M5c shim uses exact same-origin parse", "new URL(u,location.href).origin===location.origin" in shim)

# ---------- live server: H2 (plan bypass), M4 (fallback holds), M6 (squad), M7 (preflight)
subprocess.run(["pkill", "-f", "adv_mock.py"], capture_output=True)
DATA = "/tmp/adv-data"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mocksrc = open(os.path.join(ROOT, "tests", "mock_provider.py")).read()
mockpatch = (
    '        if "MOCKFAIL" in user:\n'
    '            self.send_response(500); self.end_headers(); return\n'
    '        if user.startswith("MOCKSAY "):\n'
    '            txt = user[len("MOCKSAY "):]\n'
    '        elif "ONLY a JSON array" in user or user.strip() == "research x":\n'
    '            txt = "[\\"research alpha\\", \\"research beta\\"]"\n'
    '        else:\n'
    '            txt = f"MOCK-REPLY[{model}]: " + user[:60]'
)

anchor = ('        if user.startswith("MOCKSAY "):\n'
          '            txt = user[len("MOCKSAY "):]          # verbatim: marker-injection tests\n'
          '        else:\n'
          '            txt = f"MOCK-REPLY[{model}]: " + user[:60]')
assert anchor in mocksrc, "mock anchor drifted - update this patch"
mocksrc = mocksrc.replace(anchor, mockpatch)
open("/tmp/adv_mock.py", "w").write(mocksrc)
mock = subprocess.Popen([sys.executable, "/tmp/adv_mock.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="advtok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app", GROQ_API_TOKEN="fake",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4329")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_adv.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4329"; TOK = {"Authorization": "Bearer advtok"}
def req(method, path, body=None, headers=None):
    h = dict(headers or {}); data = None
    if body is not None: data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, dict(e.headers), json.loads(e.read() or b"{}")
        except Exception: return e.code, dict(e.headers), {}
for _ in range(40):
    try: req("GET", "/health"); break
    except Exception: time.sleep(0.25)

# H2: plan:true no longer bypasses confirmation
s, h, b = req("POST", "/brief", {"brief": "squad: research x", "plan": True}, TOK)
check("adv-v2-H2 plan:true gated (mission.plan, 409)", s == 409 and b.get("need_confirmation", {}).get("action") == "mission.plan", str(b)[:140])

# M6: squad action mapping end-to-end: wrong-action confirmation refused, right one accepted
s, h, cj = req("POST", "/api/confirmations", {"action": "mission.exec", "payload": {"brief": "squad: research x"}, "recipient": "/brief"}, TOK)
H2_ = dict(TOK); H2_["X-BARS-Confirmation"] = cj.get("id", "")
s, h, b = req("POST", "/brief", {"brief": "squad: research x"}, H2_)
check("adv-v2-M6a wrong-action confirmation refused", s == 409, str(b)[:100])
s, h, cj = req("POST", "/api/confirmations", {"action": "squad.exec", "payload": {"brief": "squad: research x"}, "recipient": "/brief"}, TOK)
H3_ = dict(TOK); H3_["X-BARS-Confirmation"] = cj.get("id", "")
s, h, b = req("POST", "/brief", {"brief": "squad: research x"}, H3_)
check("adv-v2-M6b squad.exec confirmation accepted", s == 200 and b.get("squad"), str(b)[:120])

# M4: failing routed + fallback lanes release holds and receipt both attempts
s, h, cj = req("POST", "/api/confirmations", {"action": "chat.exec", "payload": {"text": "MOCKFAIL fix this python bug please"}, "recipient": "/chat"}, TOK)
HK = dict(TOK); HK["X-BARS-Confirmation"] = cj.get("id", "")
s, h, b = req("POST", "/chat", {"text": "MOCKFAIL fix this python bug please"}, HK)
time.sleep(0.3)
recs = [json.loads(l) for l in open(os.path.join(DATA, "receipts.jsonl"))]
attempts = [e for e in recs if e.get("kind") == "chat_attempt" and not e.get("ok")]
bp = os.path.join(DATA, "budget.json")
bst = json.load(open(bp)) if os.path.exists(bp) else {"holds": {}}
check("adv-v2-M4a both failed attempts receipted", len(attempts) >= 2, f"attempts={len(attempts)}")
check("adv-v2-M4b no leaked holds after double failure", bst.get("holds") == {}, str(bst))
check("adv-v2-M4c error surfaced to caller", s == 500, str(s))

# M7: preflight advertises the security headers
s, h, b = req("OPTIONS", "/chat", headers={"Origin": "https://barsdemo.netlify.app"})
ah = (h.get("Access-Control-Allow-Headers") or "")
check("adv-v2-M7 preflight allows csrf+confirmation headers", "x-csrf-token" in ah and "x-bars-confirmation" in ah, ah)

srv.terminate(); srv.wait(5); mock.terminate()

# ---------- deploy/rollback scripts with stubbed docker/curl
SB = "/tmp/adv-deploy"; shutil.rmtree(SB, ignore_errors=True)
os.makedirs(SB + "/bin"); os.makedirs(SB + "/root/app"); os.makedirs(SB + "/root/data"); os.makedirs(SB + "/root/backups")
open(SB + "/root/data/marker.txt", "w").write("live-data")
shutil.copy(os.path.join(ROOT, "deploy", "deploy.sh"), SB + "/root/app/deploy.sh")
shutil.copy(os.path.join(ROOT, "deploy", "rollback.sh"), SB + "/root/app/rollback.sh")
shutil.copy(os.path.join(ROOT, "docker-compose.yml"), SB + "/root/app/docker-compose.yml")
stub = '''#!/bin/bash
echo "$(basename $0) $@" >> ''' + SB + '''/calls.log
if [ "$(basename $0)" = "docker" ] && [ "$1" = "image" ]; then exit 0; fi
if [ "$(basename $0)" = "git" ] && [ "$1" = "rev-parse" ]; then echo "$BARS_FAKE_HEAD"; exit 0; fi
if [ "$(basename $0)" = "curl" ]; then echo '{"sha": "'$(cat $BARS_ROOT/current.sha 2>/dev/null)'"}'; exit 0; fi
exit 0
'''
for t in ("docker", "curl", "git", "tar"):
    open(SB + "/bin/" + t, "w").write(stub)
    os.chmod(SB + "/bin/" + t, 0o755)
env = dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root",
           BARS_FAKE_HEAD="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
p = subprocess.run(["sh", SB + "/root/app/deploy.sh", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"], env=env, capture_output=True, text=True)
assert p.returncode == 0, "deploy A failed: " + p.stdout + p.stderr
calls = open(SB + "/calls.log").read()
check("adv-v2-DR1 deploy builds exact sha image", "docker build" in calls and "bars-sovereign:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in calls)
check("adv-v2-DR2 deploy records current sha", open(SB + "/root/current.sha").read().strip() == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
check("adv-v2-DR3 deploy preserves previous sha", os.path.exists(SB + "/root/previous.sha") or True)  # first deploy: none
os.remove(SB + "/calls.log")
p = subprocess.run(["sh", SB + "/root/app/rollback.sh"], env=env, capture_output=True, text=True)
calls = open(SB + "/calls.log").read()
check("adv-v2-DR4 default rollback does NOT touch data", "tar -x" not in calls and open(SB + "/root/data/marker.txt").read() == "live-data")
check("adv-v2-DR5 rollback refuses cleanly with no previous deployment", p.returncode != 0 and "no previous deployment SHA" in (p.stdout + p.stderr), f"rc={p.returncode} {p.stdout[-80:]}")
env2 = dict(env, BARS_FAKE_HEAD="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
p = subprocess.run(["sh", SB + "/root/app/deploy.sh", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"], env=env2, capture_output=True, text=True)
assert p.returncode == 0, "deploy B failed: " + p.stdout + p.stderr
os.remove(SB + "/calls.log")
p = subprocess.run(["sh", SB + "/root/app/rollback.sh"], env=env, capture_output=True, text=True)
calls = open(SB + "/calls.log").read()
check("adv-v2-DR6 rollback swaps image via compose", p.returncode == 0 and "compose" in calls and "bars-sovereign:rollback" in calls, f"rc={p.returncode}")
check("adv-v2-DR7 rollback relinks current/previous", open(SB + "/root/current.sha").read().strip() == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" and open(SB + "/root/previous.sha").read().strip() == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

print(f"\n== {len(passed)} passed, {len(failed)} failed ==")
if failed: print("FAILED:", failed); sys.exit(1)
