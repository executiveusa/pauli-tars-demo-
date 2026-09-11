# BARS adversarial suite v8 - ninth-review items. Versioned: adv-v8-<n>.
import json, os, shutil, subprocess, sys, threading, time
import urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

DATA = "/tmp/v8-data"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
os.environ.update(BARS_OPERATOR_TOKEN="v8tok", BARS_DATA_DIR=DATA, BARS_TEST_MODE="1",
                  BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
                  BARS_CONFIG=os.path.join(DATA, "cfg.json"),
                  BARS_ALLOW_PAID="1", BARS_PAID_TOKEN_BUDGET="100000",
                  BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com")
json.dump({"model": {"api_key": "sk-x", "model": "m", "base_url": "http://127.0.0.1:9999/v1"}},
          open(os.path.join(DATA, "cfg.json"), "w"))
import server

class FakeResp:
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False
_orig = server.urllib.request.urlopen

# adv-v8-1: malformed usage (OpenAI-compatible) - no post-spend 500, settles at estimate
bad = json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": "garbage"}).encode()
server.urllib.request.urlopen = lambda req, **kw: FakeResp(bad)
server._cap_register("m-v8-1", 100000)
server._COST_CAP.mission = "m-v8-1"; server._COST_CAP.value = 0
reply = server.anthropic_chat("s", [{"role": "user", "content": "a"}], max_tokens=10)
used1 = server.MISSION_CAPS["m-v8-1"]["used"]
check("adv-v8-1 malformed usage: reply ok, aggregate settles at estimate, no 500",
      reply == "ok" and used1 == 10, f"reply={reply!r} used={used1}")

# adv-v8-2: malformed usage (Anthropic-native path) - same guarantees
anth = json.dumps({"content": [{"text": "ok"}], "usage": [1, 2]}).encode()
server.urllib.request.urlopen = lambda req, **kw: FakeResp(anth)
_keep_model, _keep_base = server.CONFIG["model"], server.CONFIG.get("base_url")
server.CONFIG["model"] = "claude-v8"; server.CONFIG["base_url"] = ""
server._cap_register("m-v8-2", 100000)
server._COST_CAP.mission = "m-v8-2"
err2 = None
try:
    reply2 = server.anthropic_chat("s", [{"role": "user", "content": "a"}], max_tokens=10)
except Exception as e:
    err2 = str(e); reply2 = None
used2 = server.MISSION_CAPS["m-v8-2"]["used"]
check("adv-v8-2 malformed usage (anthropic-native): no post-spend 500, settle at estimate",
      reply2 == "ok" and err2 is None and used2 == 10, f"reply={reply2!r} err={err2} used={used2}")
server.CONFIG["model"], server.CONFIG["base_url"] = _keep_model, _keep_base
server.urllib.request.urlopen = _orig

# adv-v8-3: reserve happens AFTER route selection - routed raises are covered by the reserve
import bars_router
called = {"urls": []}
def spy(req, **kw):
    called["urls"].append(req.full_url)
    return FakeResp(json.dumps({"choices": [{"message": {"content": "ok"}}],
                                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode())
server.urllib.request.urlopen = spy
_keep_route = bars_router.bars_route
os.environ["V8_FAKE_KEY"] = "k"
bars_router.bars_route = lambda um, available=None: {"model": {
    "model": "gpt-x", "base_url": "http://127.0.0.1:9999/v1", "max_tokens": 4000,
    "api_key_env": "V8_FAKE_KEY", "lane": "worker", "routing": "test"}}
server._cap_register("m-v8-3", 2500)   # pre-route est (10+2000) fits; routed est (4000+2000) does not
server._COST_CAP.mission = "m-v8-3"; server._COST_CAP.value = 0
err3 = None
try:
    server.anthropic_chat("s", [{"role": "user", "content": "hi"}], max_tokens=10, user_message="hi")
except RuntimeError as e:
    err3 = str(e)
completions = [u for u in called["urls"] if "/chat/completions" in u or u.endswith("/messages")]
check("adv-v8-3a routed raise reserved post-route: fails closed BEFORE any completion call",
      err3 and "aggregate cost cap" in err3 and not completions,
      f"err={str(err3)[:60]} urls={called['urls']}")
# adv-v8-3b: cache hits are free - no reservation is ever taken
bars_router.bars_route = lambda um, available=None: {"cache_hit": True, "cached": "cached!"}
before = server.MISSION_CAPS["m-v8-3"]["used"]
out = server.anthropic_chat("s", [{"role": "user", "content": "hi"}], max_tokens=10, user_message="hi")
check("adv-v8-3b cache hit returns without reserving against the aggregate cap",
      out == "cached!" and server.MISSION_CAPS["m-v8-3"]["used"] == before,
      f"out={out!r} used={server.MISSION_CAPS['m-v8-3']['used']}")
bars_router.bars_route = _keep_route
server.urllib.request.urlopen = _orig
server._COST_CAP.mission = None

# adv-v8-7: aggregate cap lifecycle - release works and terminals clean up
server._cap_register("m-v8-7", 100)
server._cap_release("m-v8-7")
server._cap_release("m-v8-7")   # missing key: no-op, no error
check("adv-v8-7a _cap_release removes the entry and tolerates missing keys",
      "m-v8-7" not in server.MISSION_CAPS, str(list(server.MISSION_CAPS)))
_keep_ac = server.anthropic_chat
server.anthropic_chat = lambda *a, **k: "report text"
m1 = {"id": "v8m1", "brief": "x", "status": "EN ROUTE", "cap_key": "v8m1", "events": []}
server.MISSIONS["v8m1"] = m1
server._cap_register("v8m1", 100)
server.run_internal_mission(m1)
check("adv-v8-7b completed mission releases its own aggregate cap",
      m1["status"] == "COMPLETE" and "v8m1" not in server.MISSION_CAPS,
      f"status={m1['status']} caps={list(server.MISSION_CAPS)}")
m2 = {"id": "v8m2", "brief": "x", "status": "EN ROUTE", "cap_key": "parent-x", "events": []}
server.MISSIONS["v8m2"] = m2
server._cap_register("parent-x", 100)
server.run_internal_mission(m2)
check("adv-v8-7c squad child never releases the parent's shared cap",
      "parent-x" in server.MISSION_CAPS and "v8m2" not in server.MISSION_CAPS,
      str(list(server.MISSION_CAPS)))
server.anthropic_chat = _keep_ac

# adv-v8-4: unauthenticated + authenticated body caps (live server)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=os.path.join(DATA, "live"), BARS_OPERATOR_TOKEN="v8tok",
           GROQ_API_TOKEN="fake", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1", BARS_FREE_PROVIDERS="127.0.0.1",
           BARS_ALLOW_PAID="", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4341",
           BARS_MAX_BODY_PUBLIC="1024", BARS_MAX_BODY_AUTH="4096")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_v8.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4341"
TOK = {"Authorization": "Bearer v8tok"}
def raw_req(path, raw, headers=None):
    r = urllib.request.Request(B + path, data=raw, headers=dict(headers or {}), method="POST")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]
up = False
for _ in range(60):
    try:
        urllib.request.urlopen(B + "/health", timeout=2); up = True; break
    except Exception:
        time.sleep(0.25)
assert up, "live server did not start"
s, b = raw_req("/chat", b"x" * 2000)                      # no token, over public cap
check("adv-v8-4a unauthenticated oversize body rejected 413 pre-auth", s == 413, f"{s} {b[:80]}")
s, b = raw_req("/chat", b"x" * 8000, TOK)                 # authed, over auth cap
check("adv-v8-4b authenticated oversize body rejected 413", s == 413, f"{s} {b[:80]}")
s, b = raw_req("/chat", json.dumps({"text": "ok"}).encode(), dict(TOK, **{"content-type": "application/json"}))
check("adv-v8-4c normal authed body unaffected by the cap", s == 200, f"{s} {b[:80]}")
srv.terminate(); srv.wait(5); mock.terminate()

# adv-v8-5: deploy refuses a dirty worktree BEFORE fetch/checkout
SB = "/tmp/v8-deploy"; shutil.rmtree(SB, ignore_errors=True)
os.makedirs(SB + "/bin"); os.makedirs(SB + "/root/app"); os.makedirs(SB + "/root/data"); os.makedirs(SB + "/root/backups")
for f in ("deploy.sh", "rollback.sh"):
    shutil.copy(os.path.join(ROOT, "deploy", f), SB + "/root/app/" + f)
shutil.copy(os.path.join(ROOT, "docker-compose.yml"), SB + "/root/app/docker-compose.yml")
stub = ('#!/bin/bash\necho "$(basename $0) $@" >> ' + SB + '/calls.log\n'
        'if [ "$(basename $0)" = "git" ] && [ "$1" = "status" ]; then [ -f ' + SB + '/dirty ] && echo " M x"; exit 0; fi\n'
        'if [ "$(basename $0)" = "git" ] && [ "$1" = "rev-parse" ]; then echo "$BARS_FAKE_HEAD"; exit 0; fi\n'
        'if [ "$(basename $0)" = "curl" ]; then echo "{\\"sha\\": \\"$(cat $BARS_ROOT/current.sha 2>/dev/null)\\"}"; exit 0; fi\n'
        'exit 0\n')
for t in ("docker", "curl", "git", "tar"):
    open(SB + "/bin/" + t, "w").write(stub); os.chmod(SB + "/bin/" + t, 0o755)
SHA_C = "c" * 40
def run_deploy():
    e = dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root", BARS_FAKE_HEAD=SHA_C)
    return subprocess.run(["sh", SB + "/root/app/deploy.sh", SHA_C], env=e, capture_output=True, text=True)
open(SB + "/dirty", "w").write("x")
p = run_deploy()
calls = open(SB + "/calls.log").read() if os.path.exists(SB + "/calls.log") else ""
check("adv-v8-5a dirty worktree refused BEFORE fetch/checkout",
      p.returncode == 2 and "pristine" in (p.stdout + p.stderr)
      and "git fetch" not in calls and "git checkout" not in calls,
      f"rc={p.returncode} calls={calls.strip()!r}")
os.remove(SB + "/dirty")
if os.path.exists(SB + "/calls.log"): os.remove(SB + "/calls.log")
p = run_deploy()
calls = open(SB + "/calls.log").read()
check("adv-v8-5b pristine worktree proceeds through fetch+checkout",
      p.returncode == 0 and "git fetch" in calls and "git checkout" in calls,
      f"rc={p.returncode} err={p.stderr[-80:]}")

# adv-v8-6: both Open Code Review refs are SHA-pinned (no floating @main)
wf = open(os.path.join(ROOT, ".github/workflows/vibe-code-review.yml")).read()
doc = open(os.path.join(ROOT, "docs/SOFTWARE_FACTORY_GATE.md")).read()
PIN = "864933213372cc488b3f2f2b1deaab84ea91b855"
check("adv-v8-6a reusable workflow ref is SHA-pinned",
      PIN in wf and "vibe-code-review.yml@main" not in wf, "")
check("adv-v8-6b gate doc ref is SHA-pinned",
      PIN in doc and "vibe-code-review.yml@main" not in doc, "")

print(f"{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
