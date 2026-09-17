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
        barrier.wait(timeout=5)
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
mocksrc = open(os.path.join(ROOT, "tests", "mock_provider.py")).read()
anchor = ('        if user.startswith("MOCKSAY "):\n'
          '            txt = user[len("MOCKSAY "):]          # verbatim: marker-injection tests\n'
          '        else:\n'
          '            txt = f"MOCK-REPLY[{model}]: " + user[:60]')
patch = ('        if user.startswith("MOCKSAY "):\n'
         '            txt = user[len("MOCKSAY "):]\n'
         '        elif user.strip().startswith("research presplit race"):\n'
         '            txt = "[\\"part alpha\\", \\"part beta\\"]"\n'
         '        elif user.startswith("Brief: "):\n'
         '            txt = \'{"critique": "thin sourcing.", "follow_up": "research the biggest gap v13"}\'\n'
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
# adv-v9-9: /followup registers the exact displayed 8192 bound (matching /act and /brief)
H = mint("mission.exec", {"brief": "research followup bound v13"}, "/brief")
s, h, b = req("POST", "/brief", {"brief": "research followup bound v13"}, H)
mid9 = b.get("id")
st = None
for _ in range(80):
    s, h, b = req("GET", f"/mission/{mid9}", headers=TOK)
    st = b.get("status")
    if st in ("COMPLETE", "FAILED"): break
    time.sleep(0.25)
fu = b.get("follow_up") or ""
check("adv-v9-9a mission completes with a proposed follow-up",
      st == "COMPLETE" and fu == "research the biggest gap v13", f"{st} fu={fu[:60]}")
s, h, b = req("POST", "/followup", {"id": mid9}, TOK)
check("adv-v9-9b follow-up without confirmation: 409 displays the 8192 bound",
      s == 409 and (b.get("need_confirmation") or {}).get("cost_bound") == 8192,
      f"{s} {b.get('need_confirmation')}")
s, h, b = req("POST", "/followup", {"id": mid9}, mint("mission.exec", {"id": mid9}, "/followup"))
nid9 = b.get("id")
check("adv-v9-9c follow-up with exact confirmation starts", s == 200 and bool(nid9), f"{s} {str(b)[:80]}")
s, h, b = req("GET", f"/mission/{nid9}", headers=TOK)
check("adv-v9-9d displayed bound registered into start_mission (cap_key set)",
      bool(b.get("cap_key")), f"cap_key={b.get('cap_key')}")
st = None
for _ in range(80):
    s, h, b = req("GET", f"/mission/{nid9}", headers=TOK)
    st = b.get("status")
    if st in ("COMPLETE", "FAILED"): break
    time.sleep(0.25)
check("adv-v9-9e bounded follow-up completes under its cap", st == "COMPLETE", str(st))

# adv-v9-13: a dead follow-up returns 400 BEFORE the confirmation is consumed
H13 = mint("mission.exec", {"id": "deadbeef"}, "/followup")
s, h, b = req("POST", "/followup", {"id": "deadbeef"}, H13)
r1 = (s, b.get("error"))
s, h, b = req("POST", "/followup", {"id": "deadbeef"}, H13)
r2 = (s, b.get("error"))
check("adv-v9-13 dead follow-up: 400 without consuming the single-use confirmation",
      r1[0] == 400 and r2[0] == 400 and "no follow-up" in str(r1[1]) and "no follow-up" in str(r2[1]),
      f"first={r1} second={r2}")

srv.terminate(); srv.wait(5); mock.terminate()

# adv-v9-2: OCR supply-chain pin is two levels deep and documented honestly
wf = open(os.path.join(ROOT, ".github/workflows/vibe-code-review.yml")).read()
doc = open(os.path.join(ROOT, "docs/SOFTWARE_FACTORY_GATE.md")).read()
CALLER = "2fab76c0695d83d3ddb71be8ae4bc7e498a9137c"
ACTION = "2d685ab0d057aec8255f18cd0a5f5a14fbfd5195"
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
    server._cap_reserve("squad-test", 10)
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

# adv-v9-6: the candidate never controls its judge + every BARS workflow ref pinned
import re as _re2
check("adv-v9-6a candidate rule.json is absent (trusted policy is centrally pinned)",
      not os.path.exists(os.path.join(ROOT, ".opencodereview", "rule.json"))
      and "centrally pinned policy" in doc, "")
_all_sha = True
_refs = []
for wfname in ("vibe-code-review.yml", "docker-integration.yml", "bars-check.yml"):
    txt = open(os.path.join(ROOT, ".github", "workflows", wfname)).read()
    for u in _re2.findall(r"uses:\s*([^\s#]+)", txt):
        _refs.append((wfname, u))
        if "@" not in u or not _re2.search(r"@[0-9a-f]{40}$", u):
            _all_sha = False
check("adv-v9-6b every uses: ref in all BARS workflows is a full 40-hex SHA pin",
      _all_sha and len(_refs) >= 4, str(_refs))

# adv-v9-7: evidence byte binding is published in run output + check summary
di = open(os.path.join(ROOT, ".github", "workflows", "docker-integration.yml")).read()
check("adv-v9-7 evidence hashes published in run log and step summary",
      "sha256sum docker-integration.log run-context.txt" in di
      and "GITHUB_STEP_SUMMARY" in di and "evidence-hashes.txt" in di, "")

# adv-v9-8: docker integration covers failed-health bookkeeping + with-data + fallback
td = open(os.path.join(ROOT, "tests", "test_deploy_docker.sh")).read()
check("adv-v9-8 docker test covers failed-health, --with-data cycle, snapshot fallback",
      "failed-health rollback" in td and "--with-data" in td
      and "snapshotting via" in td and "rolled-back-from.sha" in td, "")

# adv-v9-10: abort landing before the first model call still reaches a
# persisted terminal state (was: stuck ABORTING forever, no model call made)
m10 = {"id": "deadrace", "brief": "race window", "kind": "OPS", "events": [],
       "_abort": True, "status": "ABORTING", "t_start": time.time(), "t_end": None,
       "agent": "CASE", "parent": None, "cap_key": "deadrace"}
server._cap_register("deadrace", 8192)
server.MISSIONS["deadrace"] = m10
called10 = []
_orig_ac = server.anthropic_chat
server.anthropic_chat = lambda *a, **k: called10.append(1) or "SHOULD-NOT-HAPPEN"
try:
    server.run_internal_mission(m10)
finally:
    server.anthropic_chat = _orig_ac
_rec = None
try:
    _idx = json.load(open(os.path.join(server.MISSIONS_DIR, "index.json"))) or []
    _rec = next((x for x in _idx if x.get("id") == "deadrace"), None)
except Exception:
    pass
check("adv-v9-10 pre-first-call abort: ABORTED + persisted, zero model calls",
      m10["status"] == "ABORTED" and m10["t_end"] and not called10
      and _rec is not None and _rec.get("status") == "ABORTED",
      f"status={m10['status']} calls={len(called10)} persisted={(_rec or {}).get('status')}")
check("adv-v9-10b pre-call abort releases the dead solo cap",
      "deadrace" not in server.MISSION_CAPS, str(list(server.MISSION_CAPS)))
del server.MISSIONS["deadrace"]

# adv-v9-11: abort landing DURING the first model call also closes out
m11 = {"id": "midrace1", "brief": "race window post", "kind": "OPS", "events": [],
       "status": "EN ROUTE", "t_start": time.time(), "t_end": None,
       "agent": "CASE", "parent": None, "cap_key": "midrace1"}
server._cap_register("midrace1", 8192)
server.MISSIONS["midrace1"] = m11
called11 = []
def _abort_during_call(*a, **k):
    called11.append(1)
    m11["_abort"] = True
    return "report body"
server.anthropic_chat = _abort_during_call
try:
    server.run_internal_mission(m11)
finally:
    server.anthropic_chat = _orig_ac
check("adv-v9-11a post-call abort: ABORTED after exactly one model call",
      m11["status"] == "ABORTED" and m11["t_end"] and len(called11) == 1,
      f"status={m11['status']} calls={len(called11)}")
check("adv-v9-11b post-call abort releases the dead solo cap",
      "midrace1" not in server.MISSION_CAPS, str(list(server.MISSION_CAPS)))
del server.MISSIONS["midrace1"]

# adv-v9-12: a squad CHILD abort never releases the shared parent cap
m12 = {"id": "child001", "brief": "child race", "kind": "OPS", "events": [],
       "_abort": True, "status": "ABORTING", "t_start": time.time(), "t_end": None,
       "agent": "KIPP", "parent": "parentpid", "cap_key": "parentpid"}
server._cap_register("parentpid", 16384)
server.MISSIONS["child001"] = m12
server.run_internal_mission(m12)
check("adv-v9-12 aborted squad child leaves the shared parent cap registered",
      m12["status"] == "ABORTED" and "parentpid" in server.MISSION_CAPS,
      f"status={m12['status']} caps={list(server.MISSION_CAPS)}")
del server.MISSIONS["child001"]
server._cap_release("parentpid")

print(f"{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
