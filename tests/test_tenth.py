# BARS adversarial suite v9 - tenth-review items. Versioned: adv-v9-<n>.
import json, os, shutil, subprocess, sys, threading, time
import urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

DATA = "/tmp/v10-data"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
os.environ.update(BARS_OPERATOR_TOKEN="v10tok", BARS_DATA_DIR=DATA, BARS_TEST_MODE="1",
                  BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
                  BARS_CONFIG=os.path.join(DATA, "cfg.json"),
                  BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com")
json.dump({"model": {"api_key": "sk-x", "model": "m", "base_url": "http://127.0.0.1:9999/v1"}},
          open(os.path.join(DATA, "cfg.json"), "w"))
import server

# adv-v9-1a: concurrent presplit cycles can never reset or release each other's
# shown-bound accounting (unique per-request keys). Replicates the exact
# handler sequence: register -> reserve -> (overlap) -> release.
barrier = threading.Barrier(2)
errs = []
def cycle(bound, tag):
    key = "presplit:" + os.urandom(6).hex()
    server._cap_register(key, bound)
    server._COST_CAP.mission = key
    try:
        server._cap_reserve(key, 100)
        barrier.wait(timeout=5)                     # both registered+reserved now
        time.sleep(0.05)
        e = server.MISSION_CAPS.get(key)
        if not e or e["used"] != 100 or e["bound"] != bound:
            errs.append(f"{tag}: accounting disturbed: {e}")
    except Exception as ex:
        errs.append(f"{tag}: {ex}")
    finally:
        server._COST_CAP.mission = None
        server._cap_release(key)
t1 = threading.Thread(target=cycle, args=(1000, "A"))
t2 = threading.Thread(target=cycle, args=(2000, "B"))
t1.start(); t2.start(); t1.join(10); t2.join(10)
leftovers = [k for k in server.MISSION_CAPS if k.startswith("presplit")]
check("adv-v9-1a concurrent presplit cycles: independent accounting, no cross-release",
      not errs and not leftovers, f"errs={errs} leftovers={leftovers}")

# adv-v9-1b: two concurrent squad confirmations over HTTP both succeed
# patched mock: squad split needs a JSON-array reply for these briefs
mocksrc = open(os.path.join(ROOT, "tests", "mock_provider.py")).read()
anchor = ('        if user.startswith("MOCKSAY "):\n'
          '            txt = user[len("MOCKSAY "):]          # verbatim: marker-injection tests\n'
          '        else:\n'
          '            txt = f"MOCK-REPLY[{model}]: " + user[:60]')
patch = ('        if user.startswith("MOCKSAY "):\n'
         '            txt = user[len("MOCKSAY "):]\n'
         '        elif user.strip().startswith("research presplit race"):\n'
         '            txt = "[\\"part alpha\\", \\"part beta\\"]"\n'
         '        else:\n'
         '            txt = f"MOCK-REPLY[{model}]: " + user[:60]')
assert anchor in mocksrc, "mock anchor drifted"
open("/tmp/v10_mock.py", "w").write(mocksrc.replace(anchor, patch))
mock = subprocess.Popen([sys.executable, "/tmp/v10_mock.py"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=os.path.join(DATA, "live"), BARS_OPERATOR_TOKEN="v10tok",
           GROQ_API_TOKEN="fake", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1", BARS_FREE_PROVIDERS="127.0.0.1",
           BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4343")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_v10.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4343"
TOK = {"Authorization": "Bearer v10tok"}
def req(method, path, body=None, headers=None):
    h = dict(headers or {}); data = None
    if body is not None: data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, dict(e.headers), json.loads(e.read() or b"{}")
        except Exception: return e.code, dict(e.headers), {}
up = False
for _ in range(60):
    try:
        urllib.request.urlopen(B + "/health", timeout=2); up = True; break
    except Exception:
        time.sleep(0.25)
assert up, "live server did not start"
def mint(action, payload, recipient):
    s, h, cj = req("POST", "/api/confirmations", {"action": action, "payload": payload, "recipient": recipient}, TOK)
    assert s == 200 and cj.get("id"), f"mint failed {s} {cj}"
    h2 = dict(TOK); h2["X-BARS-Confirmation"] = cj["id"]
    return h2
results = {}
def squad_call(tag):
    brief = f"squad: research presplit race {tag}"
    H = mint("squad.exec", {"brief": brief}, "/brief")
    results[tag] = req("POST", "/brief", {"brief": brief}, H)
threads = [threading.Thread(target=squad_call, args=(t,)) for t in ("A", "B")]
[t.start() for t in threads]; [t.join(30) for t in threads]
ok = all(results.get(t, (0, {}, {}))[0] == 200 and results[t][2].get("squad") for t in ("A", "B"))
check("adv-v9-1b two concurrent squad confirmations both succeed independently",
      ok, json.dumps({t: results.get(t, (0,))[0] for t in ("A", "B")}))
srv.terminate(); srv.wait(5); mock.terminate()

# adv-v9-2: OCR supply-chain pin is two levels deep and documented honestly
wf = open(os.path.join(ROOT, ".github/workflows/vibe-code-review.yml")).read()
doc = open(os.path.join(ROOT, "docs/SOFTWARE_FACTORY_GATE.md")).read()
CALLER = "ca8d7a87f30b556a3f898e59d6993f076852a188"
ACTION = "079c7c28b2e10e47ff1ddd8df8f5138ea2efff79"
import re as _re
_uses = _re.findall(r"uses:\s*executiveusa/open-code-review[^\s]*", wf)
_ocrver = _re.search(r'ocr_version:\s*"([0-9]+\.[0-9]+\.[0-9]+)"', wf)
check("adv-v9-2a every OCR ref in the caller is a 40-hex SHA pin + exact ocr_version",
      _uses and all(u.endswith("@" + CALLER) for u in _uses)
      and "@main" not in wf and _ocrver and _ocrver.group(1) == "1.11.8",
      str(_uses))
check("adv-v9-2b gate doc records the two-level chain and the INFO residual",
      CALLER in doc and ACTION in doc and "INFO residual" in doc, "")

# adv-v9-3: rollback-failure behavior documented (attempted image left running,
# no bookkeeping rewrite) and base image digest-pinned
dep = open(os.path.join(ROOT, "DEPLOY.md")).read()
check("adv-v9-3a DEPLOY.md documents failed-rollback end state (behavior proven in adv-v7-9a/b)",
      "FAILED rollback leaves the attempted previous image RUNNING" in dep
      and "rewrites NO bookkeeping" in dep, "")
dk = open(os.path.join(ROOT, "Dockerfile")).read()
_from = [l for l in dk.splitlines() if l.startswith("FROM ")]
_pin = _re.search(r"^FROM \S+@sha256:[0-9a-f]{64}$", _from[0]) if _from else None
check("adv-v9-3b base image is digest-pinned (parsed FROM, no mutable tag)",
      bool(_pin) and all("@sha256:" in l for l in _from), str(_from))

# adv-v9-4: settled split actual carries into the squad cap (never zeroed)
class FakeRespU:
    def __init__(self, tin, tout):
        self.body = json.dumps({"choices": [{"message": {"content": "ok"}}],
                                "usage": {"prompt_tokens": tin, "completion_tokens": tout}}).encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False
_orig2 = server.urllib.request.urlopen
server.urllib.request.urlopen = lambda req, **kw: FakeRespU(10, 5)
server._cap_register("presplit:test", 10000)
server._COST_CAP.mission = "presplit:test"; server._COST_CAP.value = 0
server.anthropic_chat("s", [{"role": "user", "content": "a"}], max_tokens=10)
_split_used = server.MISSION_CAPS["presplit:test"]["used"]
server._cap_register("squad-test", 20)
server._cap_credit("squad-test", _split_used)
credited = server.MISSION_CAPS["squad-test"]["used"]
err4 = None
try:
    server._cap_reserve("squad-test", 10)     # 15 credited + 10 > 20 bound
except RuntimeError as e:
    err4 = str(e)
check("adv-v9-4 settled split actual credited into squad cap; bound accounts it fail-closed",
      _split_used == 15 and credited == 15 and err4 and "aggregate cost cap" in err4,
      f"split={_split_used} credited={credited} err={str(err4)[:50]}")
server._cap_release("presplit:test"); server._cap_release("squad-test")
server._COST_CAP.mission = None
server.urllib.request.urlopen = _orig2

# adv-v9-5: confirmations are bound to the minting principal
mock2 = subprocess.Popen([sys.executable, "/tmp/v10_mock.py"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env2 = dict(os.environ, BARS_DATA_DIR=os.path.join(DATA, "live2"), BARS_OPERATOR_TOKEN="v10tok",
            GROQ_API_TOKEN="fake", BARS_BASE_URL="http://127.0.0.1:9999/v1",
            BARS_GROQ_BASE="http://127.0.0.1:9999/v1", BARS_FREE_PROVIDERS="127.0.0.1",
            BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4344")
srv2 = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env2,
                        stdout=open("/tmp/bars_v10b.log", "w"), stderr=subprocess.STDOUT)
B2 = "http://127.0.0.1:4344"
up = False
for _ in range(60):
    try:
        urllib.request.urlopen(B2 + "/health", timeout=2); up = True; break
    except Exception:
        time.sleep(0.25)
assert up, "live server 2 did not start"
def req2(method, path, body=None, headers=None):
    h = dict(headers or {}); data = None
    if body is not None: data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B2 + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, dict(e.headers), json.loads(e.read() or b"{}")
        except Exception: return e.code, dict(e.headers), {}
# mint via BEARER principal
s, h, cj = req2("POST", "/api/confirmations", {"action": "mission.plan", "payload": {"brief": "squad: research presplit race P", "plan": True}, "recipient": "/brief"}, TOK)
cid = cj["id"]
# establish a SESSION principal (same token, different principal identity)
s, h, sess = req2("POST", "/api/session", {"token": "v10tok"})
cookie = h.get("Set-Cookie", "").split(";")[0]
csrf = sess.get("csrf", "")
SH = {"Cookie": cookie, "X-CSRF-Token": csrf, "X-BARS-Confirmation": cid}
s, h, b = req2("POST", "/brief", {"brief": "squad: research presplit race P", "plan": True}, SH)
check("adv-v9-5a confirmation minted by bearer is refused for a session principal",
      s == 409 and "principal mismatch" in str(b.get("error", "")), f"{s} {str(b)[:100]}")
# same-principal path still works (bearer mint + bearer consume)
s, h, cj = req2("POST", "/api/confirmations", {"action": "mission.plan", "payload": {"brief": "squad: research presplit race P", "plan": True}, "recipient": "/brief"}, TOK)
H = dict(TOK); H["X-BARS-Confirmation"] = cj["id"]
s, h, b = req2("POST", "/brief", {"brief": "squad: research presplit race P", "plan": True}, H)
check("adv-v9-5b same-principal mint+consume still succeeds", s == 200 and b.get("plan"), f"{s} {str(b)[:80]}")
srv2.terminate(); srv2.wait(5); mock2.terminate()

print(f"{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
