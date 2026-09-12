# BARS mission packaging suite - Heisenberg contract packages + state receipts.
import json, os, shutil, subprocess, sys, time
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# ---------- unit level: the contract
import mission_contract as mc

pkg = mc.build_package("research rival merch pricing", kind="OPS", cost_bound=5000,
                       cap_key="k1", skills=[{"slug": "web-research"}],
                       tools=["brightdata"], done_when="3 rivals compared")
check("mp-u1 plain brief upgrades to the full contract shape",
      pkg["objective"] == "research rival merch pricing"
      and pkg["done_when"] == "3 rivals compared"
      and pkg["inputs"]["brief"] == "research rival merch pricing"
      and pkg["allowed"] == {"tools": ["brightdata"], "skills": ["web-research"]}
      and pkg["budget"] == {"cost_bound": 5000, "cap_key": "k1"}
      and pkg["gates"]["confirmation"] == "mission.exec"
      and pkg["receipt_format"], str(pkg)[:200])
check("mp-u2 default done_when fills when not given",
      mc.build_package("x")["done_when"] == mc.DEFAULT_DONE_WHEN)
check("mp-u3 valid package passes validation", mc.validate_package(pkg) == [])
check("mp-u4 missing objective rejected",
      mc.validate_package(mc.build_package("")) != [])
bad = mc.build_package("x"); bad["done_when"] = "  "
check("mp-u5 empty done_when rejected", mc.validate_package(bad) != [])
bad = mc.build_package("x"); bad["gates"]["confirmation"] = "none"
check("mp-u6 package without the mission.exec gate rejected",
      mc.validate_package(bad) != [])

# ---------- live server
DATA = "/tmp/pkg-data"
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="mptok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app",
           GROQ_API_TOKEN="fake-token", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_GIT_SHA="mpsha1", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
           BARS_PORT="4334")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_pkg.log", "w"), stderr=subprocess.STDOUT)

B = "http://127.0.0.1:4334"
TOK = {"Authorization": "Bearer mptok"}
def req(method, path, body=None, headers=None):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, dict(e.headers), json.loads(e.read() or b"{}")
        except Exception:
            return e.code, dict(e.headers), {}

for _ in range(40):
    try:
        s, _, _ = req("GET", "/health"); break
    except Exception:
        time.sleep(0.25)
check("mp-s0 server up", s == 200, str(s))

def mint(action, payload, recipient):
    s, h, cj = req("POST", "/api/confirmations",
                   {"action": action, "payload": payload, "recipient": recipient}, TOK)
    assert s == 200 and cj.get("id"), f"mint failed {s} {cj}"
    h2 = dict(TOK); h2["X-BARS-Confirmation"] = cj["id"]
    return h2

payload = {"brief": "research rival merch pricing", "done_when": "3 rivals compared on price"}
s, h, b = req("POST", "/brief", payload, mint("mission.exec", payload, "/brief"))
check("mp-s1 mission launched with explicit done_when", s == 200 and b.get("id"), str(b)[:120])
mid = b.get("id")
for _ in range(80):
    s, h, b = req("GET", f"/mission/{mid}", headers=TOK)
    if b.get("status") != "EN ROUTE":
        break
    time.sleep(0.5)
pkg = b.get("package") or {}
check("mp-s2 mission record carries the Heisenberg package",
      b.get("status") == "COMPLETE"
      and pkg.get("objective") == "research rival merch pricing"
      and pkg.get("done_when") == "3 rivals compared on price"
      and pkg.get("allowed", {}).get("skills")
      and pkg.get("gates", {}).get("confirmation") == "mission.exec"
      and pkg.get("receipt_format"),
      str(b.get("status")) + " " + str(pkg)[:220])
check("mp-s3 mission returns updated state per receipt",
      int(b.get("state_receipts") or 0) >= 2, str(b.get("state_receipts")))

rp = os.path.join(DATA, "receipts.jsonl")
rec = [json.loads(l) for l in open(rp)]
ms = [r for r in rec if r.get("kind") == "mission_state" and r.get("mission") == mid]
check("mp-s4 state transitions receipted (EN ROUTE then COMPLETE)",
      [r["to"] for r in ms] == ["EN ROUTE", "COMPLETE"], str(ms)[:200])

payload2 = {"brief": "x", "done_when": "   "}
s, h, b = req("POST", "/brief", payload2, mint("mission.exec", payload2, "/brief"))
check("mp-s5 empty done_when refused with 400", s == 400, str(s))

srv.terminate(); mock.terminate()
print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILURES:", failed); sys.exit(1)
