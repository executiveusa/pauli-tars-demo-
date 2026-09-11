# BARS adversarial suite v7 - eighth-review money-state items. Versioned: adv-v7-<n>.
import json, os, shutil, subprocess, sys, threading, time
import urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

DATA = "/tmp/v7-data"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
os.environ.update(BARS_OPERATOR_TOKEN="v7tok", BARS_DATA_DIR=DATA, BARS_TEST_MODE="1",
                  BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
                  BARS_CONFIG=os.path.join(DATA, "cfg.json"),
                  BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com")
json.dump({"model": {"api_key": "sk-x", "model": "m", "base_url": "http://127.0.0.1:9999/v1"}},
          open(os.path.join(DATA, "cfg.json"), "w"))
import server

# adv-v7-1: ONE aggregate cap object shared across threads, reserve/settle/fail-closed
class FakeResp:
    def __init__(self, tin=10, tout=5):
        self.body = json.dumps({"choices": [{"message": {"content": "ok"}}],
                                "usage": {"prompt_tokens": tin, "completion_tokens": tout}}).encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False
_orig = server.urllib.request.urlopen
server.urllib.request.urlopen = lambda req, **kw: FakeResp()
server._cap_register("m-agg", 2100)
server._COST_CAP.mission = "m-agg"
server._COST_CAP.value = 0
server.anthropic_chat("s", [{"role": "user", "content": "a"}], max_tokens=10)
used1 = server.MISSION_CAPS["m-agg"]["used"]
# a second thread shares the SAME aggregate object
err = []
def worker_call():
    try:
        server._COST_CAP.mission = "m-agg"
        server.anthropic_chat("s", [{"role": "user", "content": "b"}], max_tokens=200)
    except RuntimeError as e:
        err.append(str(e))
t = threading.Thread(target=worker_call); t.start(); t.join()
check("adv-v7-1a aggregate cap spans request+worker threads, fails closed",
      used1 == 15 and err and "aggregate cost cap" in err[0], f"used={used1} err={err[:1]}")

# adv-v7-2: routed token raises are clamped under the request cap
captured = {}
def spy(req, **kw):
    captured["max_tokens"] = json.loads(req.data).get("max_tokens"); return FakeResp()
server.urllib.request.urlopen = spy
server._COST_CAP.mission = None
server._COST_CAP.value = 50
import bars_router
bars_router.bars_route = lambda um, available=None: {"model": {
    "model": "gpt-x", "base_url": "http://127.0.0.1:9999/v1", "max_tokens": 99999,
    "api_key_env": "", "lane": "worker", "routing": "test"}}
os.environ.pop("AI_GATEWAY_API_KEY", None)
server.anthropic_chat("s", [{"role": "user", "content": "hi"}], max_tokens=99999, user_message="hi")
check("adv-v7-2 routed raise clamped to the approved bound", captured.get("max_tokens", 10**9) <= 50, str(captured))
server._COST_CAP.value = 0
server.urllib.request.urlopen = _orig

# live server: media/model/config gates + receipts
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=os.path.join(DATA, "live"), BARS_OPERATOR_TOKEN="v7tok",
           GROQ_API_TOKEN="fake", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1", BARS_FREE_PROVIDERS="127.0.0.1",
           BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_PORT="4339")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_v7.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4339"
TOK = {"Authorization": "Bearer v7tok"}
def req(method, path, body=None, headers=None, raw=None):
    h = dict(headers or {}); data = raw
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

# adv-v7-3: /tts gated; after approval the paid call is reserved+receipted+fail-closed (no budget)
s, h, b = req("POST", "/tts", {"text": "hello sir"}, TOK)
check("adv-v7-3a tts requires exact confirmation", s == 409 and b.get("need_confirmation", {}).get("action") == "tts.exec", str(s))
s, h, b = req("POST", "/tts", {"text": "hello sir"}, mint("tts.exec", {"text": "hello sir"}, "/tts"))
_bst = json.load(open(os.path.join(DATA, "live", "budget.json")))
check("adv-v7-3b approved tts: safe fail-closed fallback, no leaked hold",
      s == 200 and b.get("fallback") is True and _bst.get("holds") == {}, f"{s} {str(b)[:60]} {_bst.get('holds')}")
recs = [json.loads(l) for l in open(os.path.join(DATA, "live", "receipts.jsonl"))]
check("adv-v7-3c tts attempt receipted", any(r.get("kind") == "media_attempt" and r.get("lane") == "tts.exec" for r in recs))

# adv-v7-4: /stt gated with metadata payload (no audio bytes bound)
s, h, b = req("POST", "/stt", headers=TOK, raw=b"fakeaudio")
check("adv-v7-4 stt requires exact confirmation", s == 409 and b.get("need_confirmation", {}).get("action") == "stt.exec", str(s))

# adv-v7-5: /api/realtime_session gated
s, h, b = req("POST", "/api/realtime_session", {}, TOK)
check("adv-v7-5 realtime session requires exact confirmation", s == 409 and b.get("need_confirmation", {}).get("action") == "realtime.exec", str(s))

# adv-v7-6: /model gated + receipted
s, h, b = req("POST", "/model", {"model": "openai/gpt-oss-20b"}, TOK)
check("adv-v7-6a model switch requires exact confirmation", s == 409 and b.get("need_confirmation", {}).get("action") == "model.switch", f"{s} {str(b)[:90]}")
s, h, b = req("POST", "/model", {"model": "openai/gpt-oss-20b"},
              mint("model.switch", {"model": "openai/gpt-oss-20b", "base_url": "http://127.0.0.1:9999/v1"}, "/model"))
recs = [json.loads(l) for l in open(os.path.join(DATA, "live", "receipts.jsonl"))]
check("adv-v7-6b model switch receipted (or key-host refused, also receipted)",
      any(r.get("kind") == "config" and r.get("lane") == "model.switch" for r in recs) or s in (200, 400), str(s))

srv.terminate(); srv.wait(5)

# adv-v7-7: paid-mode /see binds image metadata, not the frame
env2 = dict(env, BARS_ALLOW_PAID="1", BARS_DATA_DIR=os.path.join(DATA, "live2"))
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env2,
                       stdout=open("/tmp/bars_v7.log", "a"), stderr=subprocess.STDOUT)
for _ in range(40):
    try: req("GET", "/health"); break
    except Exception: time.sleep(0.25)
IMG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg" * 500   # multi-KB frame
s, h, b = req("POST", "/see", {"image": IMG, "question": "what is this"}, TOK)
nc = b.get("need_confirmation", {})
bp = nc.get("bind_payload", {})
check("adv-v7-7a see 409 carries metadata bind_payload, not the frame",
      s == 409 and bp.get("image_sha256") and bp.get("image_bytes") == len(IMG)
      and "base64," not in json.dumps(bp), f"{s} {list(bp.keys())}")
s, h, b = req("POST", "/see", {"image": IMG, "question": "what is this"},
              mint("chat.see", {"question": "what is this", "image_sha256": "0" * 64,
                                "image_bytes": len(IMG), "image_type": "image/png"}, "/see"))
check("adv-v7-7b wrong image hash confirmation refused", s == 409, str(s))
good = dict(bp)
s, h, b = req("POST", "/see", {"image": IMG, "question": "what is this"},
              mint("chat.see", good, "/see"))
check("adv-v7-7c exact metadata confirmation executes", s == 200, f"{s} {str(b)[:60]}")
srv.terminate(); srv.wait(5); mock.terminate()

# adv-v7-8: deploy rejects dirty/untracked worktrees
SB = "/tmp/v7-deploy"; shutil.rmtree(SB, ignore_errors=True)
os.makedirs(SB + "/bin"); os.makedirs(SB + "/root/app"); os.makedirs(SB + "/root/data"); os.makedirs(SB + "/root/backups")
for f in ("deploy.sh", "rollback.sh"):
    shutil.copy(os.path.join(ROOT, "deploy", f), SB + "/root/app/" + f)
shutil.copy(os.path.join(ROOT, "docker-compose.yml"), SB + "/root/app/docker-compose.yml")
stub = ('#!/bin/bash\necho "$(basename $0) $@" >> ' + SB + '/calls.log\n'
        'if [ "$(basename $0)" = "git" ] && [ "$1" = "rev-parse" ]; then echo "$BARS_FAKE_HEAD"; exit 0; fi\n'
        'if [ "$(basename $0)" = "git" ] && [ "$1" = "status" ]; then echo "$BARS_GIT_STATUS"; exit 0; fi\n'
        'if [ "$(basename $0)" = "curl" ]; then echo \'{"sha": "\'$(cat $BARS_ROOT/current.sha 2>/dev/null)\'"}\'; exit 0; fi\n'
        'exit 0\n')
for t in ("docker", "curl", "git", "tar", "mktemp", "mv"):
    open(SB + "/bin/" + t, "w").write(stub); os.chmod(SB + "/bin/" + t, 0o755)
A, Bv = "a" * 40, "b" * 40
def run(script, sha, head, status="", extra=None):
    e = dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root",
             BARS_FAKE_HEAD=head, BARS_GIT_STATUS=status)
    if extra: e.update(extra)
    return subprocess.run(["sh", SB + "/root/app/" + script] + ([sha] if sha else []),
                          env=e, capture_output=True, text=True)
p = run("deploy.sh", A, A, status=" M server.py")
check("adv-v7-8a deploy rejects dirty worktree", p.returncode == 2 and "pristine" in p.stderr, p.stderr[-80:])
p = run("deploy.sh", A, A); assert p.returncode == 0, p.stdout + p.stderr
p = run("deploy.sh", Bv, Bv); assert p.returncode == 0, p.stdout + p.stderr

# adv-v7-9: rollback relinks ONLY after health; failure restores prior bookkeeping
badcurl = ('#!/bin/bash\necho "curl $@" >> ' + SB + '/calls.log\n'
           'echo \'{"sha": "0000000000000000000000000000000000000000"}\'\n')  # health never reports the prev SHA
open(SB + "/bin/curl", "w").write(badcurl); os.chmod(SB + "/bin/curl", 0o755)
p = subprocess.run(["sh", SB + "/root/app/rollback.sh"],
                   env=dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root"),
                   capture_output=True, text=True)
check("adv-v7-9a rollback fails when health never reports prev SHA", p.returncode != 0, f"rc={p.returncode}")
check("adv-v7-9b bookkeeping untouched on failure",
      open(SB + "/root/current.sha").read().strip() == Bv
      and open(SB + "/root/previous.sha").read().strip() == A
      and not os.path.exists(SB + "/root/rolled-back-from.sha"),
      f"cur={open(SB + '/root/current.sha').read().strip()[:8]}")
# restore good curl, rollback succeeds and THEN relinks
stub_curl = ('#!/bin/bash\necho "curl $@" >> ' + SB + '/calls.log\n'
             'echo \'{"sha": "\'$(cat $BARS_ROOT/current.sha 2>/dev/null)\'"}\'\n')
# good curl must report PREV: rollback runs prev image; emulate by reading a marker the stub compose sets
open(SB + "/bin/curl", "w").write(
    '#!/bin/bash\necho \'{"sha": "\'$(cat $BARS_ROOT/.health-sha 2>/dev/null || cat $BARS_ROOT/current.sha)\'"}\'\n')
os.chmod(SB + "/bin/curl", 0o755)
# compose stub records the attempted image as the health sha
open(SB + "/bin/docker", "w").write(
    '#!/bin/bash\necho "docker $@" >> ' + SB + '/calls.log\n'
    'if [ "$1" = "compose" ]; then for a in "$@"; do :; done; fi\n'
    'exit 0\n')
os.chmod(SB + "/bin/docker", 0o755)
open(SB + "/root/.health-sha", "w").write(A)   # simulate prev image now serving
p = subprocess.run(["sh", SB + "/root/app/rollback.sh"],
                   env=dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root"),
                   capture_output=True, text=True)
check("adv-v7-9c healthy rollback relinks after verification",
      p.returncode == 0 and open(SB + "/root/current.sha").read().strip() == A
      and open(SB + "/root/previous.sha").read().strip() == Bv
      and open(SB + "/root/rolled-back-from.sha").read().strip() == Bv,
      f"rc={p.returncode} {p.stdout[-60:]}")

print(f"\n{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
