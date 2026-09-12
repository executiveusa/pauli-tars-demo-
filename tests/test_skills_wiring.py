# BARS skills wiring suite - vendored library, pin sync, smallest-relevant-set selection.
import json, os, shutil, subprocess, sys, time
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# ---------- unit level
import skills_select

cards = skills_select.load_cards()
check("sk-u1 all 81 reviewed cards vendored", len(cards) == 81, str(len(cards)))
check("sk-u2 every card pinned and byte-identical to SOURCE.json",
      all(c["pin_ok"] for c in cards), str([c["slug"] for c in cards if not c["pin_ok"]])[:120])

sel = skills_select.select("audit the accessibility of our checkout page")
check("sk-u3 accessibility brief selects the accessibility card",
      sel and sel[0]["slug"] == "accessibility-audit", str([c["slug"] for c in sel]))
sel = skills_select.select("research the web for rival merch pricing")
check("sk-u4 web research brief selects web-research",
      any(c["slug"] == "web-research" for c in sel), str([c["slug"] for c in sel]))
check("sk-u5 smallest relevant set: capped and non-empty overlap only",
      1 <= len(sel) <= 3, str(len(sel)))
sel_none = skills_select.select("zqxwv jklpm nnn")
check("sk-u6 no overlap selects nothing", sel_none == [], str([c["slug"] for c in sel_none]))

ms = skills_select.mission_skills("research the web for rival merch pricing")
check("sk-u7 mission package carries pinned skill records",
      ms and all("sha256" in m and m["pin_ok"] for m in ms), str(ms)[:200])
block = skills_select.skills_block("research the web for rival merch pricing")
check("sk-u8 prompt block carries the pinned card body",
      "SELECTED SKILL CARDS" in block and "sha256" in block, block[:120])

r = subprocess.run([sys.executable, "scripts/check_skills_sync.py"], cwd=ROOT,
                   capture_output=True, text=True)
check("sk-u9 sync check passes", r.returncode == 0, (r.stdout + r.stderr).strip()[:120])

# pin verification actually fails on drift
p = os.path.join(ROOT, "skills", "library", "web-research.md")
orig = open(p, "rb").read()
try:
    open(p, "ab").write(b"drift")
    r = subprocess.run([sys.executable, "scripts/check_skills_sync.py"], cwd=ROOT,
                       capture_output=True, text=True)
    check("sk-u10 sync check catches drift", r.returncode != 0, (r.stdout + r.stderr).strip()[:120])
    cards2 = skills_select.load_cards()
    check("sk-u11 drifted card fails pin check",
          not next(c for c in cards2 if c["slug"] == "web-research")["pin_ok"])
finally:
    open(p, "wb").write(orig)
r = subprocess.run([sys.executable, "scripts/check_skills_sync.py"], cwd=ROOT,
                   capture_output=True, text=True)
check("sk-u12 restored library passes again", r.returncode == 0)

# ---------- live server: mission packages carry skills
DATA = "/tmp/skills-data"
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="sktok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app",
           GROQ_API_TOKEN="fake-token", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_GIT_SHA="sksha1", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
           BARS_PORT="4333")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_skills.log", "w"), stderr=subprocess.STDOUT)

B = "http://127.0.0.1:4333"
TOK = {"Authorization": "Bearer sktok"}
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
check("sk-s0 server up", s == 200, str(s))

s, h, cj = req("POST", "/api/confirmations",
               {"action": "mission.exec",
                "payload": {"brief": "research the web for rival merch pricing"},
                "recipient": "/brief"}, TOK)
H = dict(TOK); H["X-BARS-Confirmation"] = cj["id"]
s, h, b = req("POST", "/brief", {"brief": "research the web for rival merch pricing"}, H)
check("sk-s1 mission launched", s == 200 and b.get("id"), str(b)[:120])
mid = b.get("id")
for _ in range(80):
    s, h, b = req("GET", f"/mission/{mid}", headers=TOK)
    if b.get("status") != "EN ROUTE":
        break
    time.sleep(0.5)
check("sk-s2 mission package carries the pinned skill set",
      b.get("status") == "COMPLETE"
      and any(sk["slug"] == "web-research" and sk["pin_ok"] for sk in b.get("skills", [])),
      str(b.get("status")) + " " + str(b.get("skills"))[:200])

srv.terminate(); mock.terminate()
print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILURES:", failed); sys.exit(1)
