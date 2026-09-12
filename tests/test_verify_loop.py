# BARS verify loop suite - ground-or-hedge in /chat + judge-lane mission seal.
import json, os, shutil, subprocess, sys, time
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# ---------- unit level: verify module
import verify

claims = verify.detect_claims("The drop is $45 on Friday. It is live now. The sky is blue.")
kinds = sorted(c["kind"] for c in claims)
check("vf-u1 detects price, date and status claims",
      "price" in kinds and "date" in kinds and "status" in kinds, str(kinds))
check("vf-u2 no claims in plain chat",
      verify.detect_claims("locked, working on it") == [])

r = verify.verify_reply("the hoodie is $45", "the Commander said: the hoodie is $45")
check("vf-u3 grounded claim ships unhedged",
      r["reply"] == "the hoodie is $45" and r["hedged"] == [] and r["claims"] == 1, str(r))
r = verify.verify_reply("the hoodie is $45 and it ships on Friday", "the Commander likes hoodies")
check("vf-u4 ungrounded claims get hedged and named",
      "Not verified" in r["reply"] and r["hedged"], str(r)[:200])
r = verify.verify_reply("the hoodie is $45", "the hoodie is $60")
check("vf-u5 a different remembered price does not ground the claim",
      "Not verified" in r["reply"], str(r)[:160])

# ---------- live server
DATA = "/tmp/verify-data"
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mocksrc = open(os.path.join(ROOT, "tests", "mock_provider.py")).read()
anchor = ('        if user.startswith("MOCKSAY "):\n'
          '            txt = user[len("MOCKSAY "):]          # verbatim: marker-injection tests\n'
          '        else:\n'
          '            txt = f"MOCK-REPLY[{model}]: " + user[:60]')
assert anchor in mocksrc, "mock anchor drifted - update this patch"
patch = ('        if user.startswith("MOCKCLAIM "):\n'
         '            txt = "the drop is $60 tomorrow and it is live now"\n'
         '        elif "JUDGE-VERIFY" in user:\n'
         '            if "EXPECT-SEAL" in user:\n'
         '                txt = \'{"verified": true, "unverified": [], "reason": "every changeable claim is backed by the report evidence"}\'\n'
         '            else:\n'
         '                txt = \'{"verified": false, "unverified": ["price claim"], "reason": "report asserts a price with no evidence"}\'\n'
         '        elif ' + anchor[len('        if '):])
mocksrc = mocksrc.replace(anchor, patch)
open("/tmp/verify_mock.py", "w").write(mocksrc)
mock = subprocess.Popen([sys.executable, "/tmp/verify_mock.py"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="vftok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app",
           GROQ_API_TOKEN="fake-token", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_GIT_SHA="vfsha1", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
           BARS_PORT="4331")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_verify.log", "w"), stderr=subprocess.STDOUT)

B = "http://127.0.0.1:4331"
TOK = {"Authorization": "Bearer vftok"}
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
check("vf-s0 server up", s == 200, str(s))

def mint(action, payload, recipient):
    s, h, cj = req("POST", "/api/confirmations",
                   {"action": action, "payload": payload, "recipient": recipient}, TOK)
    assert s == 200 and cj.get("id"), f"mint failed {s} {cj}"
    h2 = dict(TOK); h2["X-BARS-Confirmation"] = cj["id"]
    return h2

# /chat ground-or-hedge
s, h, b = req("POST", "/remember", {"text": "the hoodie is $45"}, TOK)
check("vf-s1 remembered stated fact", s == 200, str(s))
s, h, b = req("POST", "/chat", {"text": "MOCKSAY the hoodie is $45"}, TOK)
check("vf-s2 claim grounded by stated memory ships clean",
      s == 200 and b.get("reply") == "the hoodie is $45"
      and b.get("verify", {}).get("hedged") == [] and b.get("verify", {}).get("claims") >= 1,
      str(b.get("reply"))[:160])
s, h, b = req("POST", "/chat", {"text": "MOCKCLAIM what is the drop situation"}, TOK)
check("vf-s3 ungrounded price+date hedged before shipping",
      s == 200 and "Not verified" in str(b.get("reply"))
      and b.get("verify", {}).get("hedged"), str(b.get("reply"))[:220])
s, h, b = req("POST", "/chat", {"text": "MOCKSAY the show is at 9pm"}, TOK)
check("vf-s4 claim the Commander just stated is grounded by the conversation",
      s == 200 and b.get("verify", {}).get("hedged") == [], str(b.get("reply"))[:160])
s, h, b = req("POST", "/chat", {"text": "ok"}, TOK)
check("vf-s5 plain replies untouched", s == 200 and b.get("reply") == "Locked."
      and b.get("verify", {}).get("claims") == 0, str(b.get("reply"))[:120])

# judge lane seals mission reports
s, h, b = req("POST", "/brief", {"brief": "research EXPECT-SEAL competitor pricing"},
              mint("mission.exec", {"brief": "research EXPECT-SEAL competitor pricing"}, "/brief"))
check("vf-s6 mission 1 launched", s == 200 and b.get("id"), str(b)[:120])
mid1 = b.get("id")
for _ in range(80):
    s, h, b = req("GET", f"/mission/{mid1}", headers=TOK)
    if b.get("status") != "EN ROUTE":
        break
    time.sleep(0.5)
check("vf-s7 mission 1 complete and judge-sealed",
      b.get("status") == "COMPLETE"
      and (b.get("verification") or {}).get("sealed") is True
      and b["verification"]["status"] == "verified",
      str(b.get("status")) + " " + str(b.get("verification"))[:200])
rep = open(os.path.join(DATA, "missions", mid1, "report.md")).read()
check("vf-s8 sealed report carries the verification section",
      "## Verification" in rep and "SEALED" in rep)

s, h, b = req("POST", "/brief", {"brief": "research competitor pricing"},
              mint("mission.exec", {"brief": "research competitor pricing"}, "/brief"))
mid2 = b.get("id")
for _ in range(80):
    s, h, b = req("GET", f"/mission/{mid2}", headers=TOK)
    if b.get("status") != "EN ROUTE":
        break
    time.sleep(0.5)
check("vf-s9 mission 2 complete but NOT sealed when judge cannot verify",
      b.get("status") == "COMPLETE"
      and (b.get("verification") or {}).get("sealed") is False
      and b["verification"]["status"] == "unverified"
      and b["verification"].get("unverified"),
      str(b.get("status")) + " " + str(b.get("verification"))[:220])
rep = open(os.path.join(DATA, "missions", mid2, "report.md")).read()
check("vf-s10 unsealed report says so", "UNSEALED" in rep)

rp = os.path.join(DATA, "receipts.jsonl")
rec = [json.loads(l) for l in open(rp)]
check("vf-s11 judge lane calls receipted with the judge lane",
      any(r.get("lane") == "judge" for r in rec),
      str({r.get("lane") for r in rec}))

srv.terminate(); mock.terminate()
print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILURES:", failed); sys.exit(1)
