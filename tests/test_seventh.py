# BARS adversarial suite v6 - seventh-review items. Versioned: adv-v6-<n>.
import json, os, shutil, subprocess, sys, time
import urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bars_security as sec

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

DATA = "/tmp/v6-data"; shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)

# adv-v6-1: runtime identity from image-baked provenance, env is fallback only
os.environ.update(BARS_OPERATOR_TOKEN="v6tok", BARS_DATA_DIR=DATA,
                  BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_TEST_MODE="1",
                  BARS_GIT_SHA="e" * 40, BARS_SHA_FILE="/tmp/v6-data/.bars_sha")
open("/tmp/v6-data/.bars_sha", "w").write("f" * 40)
import importlib, server
importlib.reload(server)
check("adv-v6-1a baked image SHA beats env echo", server.GIT_SHA == "f" * 40, server.GIT_SHA[:8])
os.remove("/tmp/v6-data/.bars_sha")
importlib.reload(server)
check("adv-v6-1b env fallback only when no baked file", server.GIT_SHA == "e" * 40, server.GIT_SHA[:8])
# override is TEST-MODE ONLY: without BARS_TEST_MODE the file is ignored
open("/tmp/v6-data/.bars_sha", "w").write("f" * 40)
del os.environ["BARS_TEST_MODE"]
importlib.reload(server)
check("adv-v6-1c SHA_FILE ignored outside test mode", server.GIT_SHA == "e" * 40, server.GIT_SHA[:8])
os.remove("/tmp/v6-data/.bars_sha")

# adv-v6-2: receipt HMAC key from env (Infisical), file untouched
RD = "/tmp/v6-rec"; shutil.rmtree(RD, ignore_errors=True); os.makedirs(RD)
os.environ["BARS_RECEIPT_KEY"] = "ab" * 32
r = sec.ReceiptLedger(os.path.join(RD, "receipts.jsonl"), os.path.join(RD, ".k"))
r.append({"kind": "k"})
check("adv-v6-2a env key used, no key file on data volume",
      not os.path.exists(os.path.join(RD, ".k")) and r.verify()[0])
r2 = sec.ReceiptLedger(os.path.join(RD, "receipts.jsonl"), os.path.join(RD, ".k"))
check("adv-v6-2b chain verifies across processes with env key", r2.verify()[0])
os.environ["BARS_RECEIPT_KEY"] = "zz-not-hex"
try:
    sec.ReceiptLedger(os.path.join(RD, "r2.jsonl"), os.path.join(RD, ".k2"))
    check("adv-v6-2c invalid env key fails closed", False)
except Exception as e:
    check("adv-v6-2c invalid env key fails closed", "BARS_RECEIPT_KEY" in str(e), str(e)[:60])
del os.environ["BARS_RECEIPT_KEY"]

# adv-v6-3: enforced cost cap: confirmed execution never exceeds the shown bound
os.environ.update(BARS_CONFIG=os.path.join(DATA, "cfg.json"),
                  BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com")
json.dump({"model": {"api_key": "sk-x", "model": "m", "base_url": "http://127.0.0.1:9999/v1"}},
          open(os.path.join(DATA, "cfg.json"), "w"))
importlib.reload(server)
captured = {}
class FakeResp:
    def read(self): return json.dumps({"choices": [{"message": {"content": "ok"}}],
                                       "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False
def spy(req, **kw):
    captured["max_tokens"] = json.loads(req.data).get("max_tokens"); return FakeResp()
_orig_urlopen = server.urllib.request.urlopen
server.urllib.request.urlopen = spy
server._COST_CAP.value = 100
server.anthropic_chat("s", [{"role": "user", "content": "hi"}], max_tokens=99999)
check("adv-v6-3 execution clamped to the displayed bound", captured.get("max_tokens") == 100, str(captured))
server._COST_CAP.value = 0
server.urllib.request.urlopen = _orig_urlopen

# adv-v6-4: GET /api/hands requires auth (live server)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
# hands enabled via a stub module to exercise the route behind auth
env = dict(os.environ, BARS_DATA_DIR=os.path.join(DATA, "d2"), BARS_OPERATOR_TOKEN="v6tok",
           GROQ_API_TOKEN="fake", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1", BARS_FREE_PROVIDERS="127.0.0.1",
           BARS_NO_BROWSER="1", BARS_PORT="4338")
env.pop("BARS_DISABLE_HANDS", None)
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_v6.log", "w"), stderr=subprocess.STDOUT)
B = "http://127.0.0.1:4338"
TOK = {"Authorization": "Bearer v6tok"}
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
s, h, b = req("GET", "/api/hands")
check("adv-v6-4a hands events endpoint authed (401 unauth)", s == 401, str(s))
s, h, b = req("GET", "/api/hands", headers=TOK)
check("adv-v6-4b hands events reachable with auth", s == 200, str(s))

# adv-v6-5: paid conversational mode gates chat and see
srv.terminate(); srv.wait(5)
env["BARS_ALLOW_PAID"] = "1"; env["BARS_DISABLE_HANDS"] = "1"
env["BARS_DATA_DIR"] = os.path.join(DATA, "d3")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_v6.log", "a"), stderr=subprocess.STDOUT)
for _ in range(40):
    try: req("GET", "/health"); break
    except Exception: time.sleep(0.25)
s, h, b = req("POST", "/chat", {"text": "hello"}, TOK)
check("adv-v6-5a paid mode: chat itself needs approval", s == 409 and b.get("need_confirmation", {}).get("action") == "chat.exec", f"{s} {b.get('need_confirmation')}")
s, h, b = req("POST", "/see", {"image": "data:image/png;base64,iVBORw0KGgo=", "question": "hi"}, TOK)
check("adv-v6-5b paid mode: see itself needs approval", s == 409 and b.get("need_confirmation", {}).get("action") == "chat.see", f"{s}")
srv.terminate(); srv.wait(5); mock.terminate()

# adv-v6-6: rollback uses immutable prev image (stub harness, inspect enforced)
SB = "/tmp/v6-deploy"; shutil.rmtree(SB, ignore_errors=True)
os.makedirs(SB + "/bin"); os.makedirs(SB + "/root/app"); os.makedirs(SB + "/root/data"); os.makedirs(SB + "/root/backups")
for f in ("deploy.sh", "rollback.sh"):
    shutil.copy(os.path.join(ROOT, "deploy", f), SB + "/root/app/" + f)
shutil.copy(os.path.join(ROOT, "docker-compose.yml"), SB + "/root/app/docker-compose.yml")
stub = ('#!/bin/bash\necho "$(basename $0) $@" >> ' + SB + '/calls.log\n'
        'if [ "$(basename $0)" = "docker" ] && [ "$1" = "image" ] && [ "$2" = "inspect" ] && [ "$3" = "bars-sovereign:missing" ]; then exit 1; fi\n'
        'if [ "$(basename $0)" = "git" ] && [ "$1" = "rev-parse" ]; then echo "$BARS_FAKE_HEAD"; exit 0; fi\n'
        'if [ "$(basename $0)" = "curl" ]; then echo \'{"sha": "\'$(cat $BARS_ROOT/current.sha 2>/dev/null)\'"}\'; exit 0; fi\n'
        'exit 0\n')
for t in ("docker", "curl", "git", "tar", "mktemp", "mv"):
    open(SB + "/bin/" + t, "w").write(stub); os.chmod(SB + "/bin/" + t, 0o755)
A, Bv = "a" * 40, "b" * 40
def run(script, sha, head):
    e = dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root", BARS_FAKE_HEAD=head)
    return subprocess.run(["sh", SB + "/root/app/" + script] + ([sha] if sha else []),
                          env=e, capture_output=True, text=True)
p = run("deploy.sh", A, A); assert p.returncode == 0, p.stdout + p.stderr
p = run("deploy.sh", Bv, Bv); assert p.returncode == 0, p.stdout + p.stderr
# poison: immutable prev image "missing" -> rollback must fail closed
p = subprocess.run(["sh", "-c",
    f"sed -i 's/bars-sovereign:missing/bars-sovereign:{'a'*40}/' {SB}/bin/docker && sh {SB}/root/app/rollback.sh"],
    env=dict(os.environ, PATH=SB + "/bin:/usr/bin:/bin", BARS_ROOT=SB + "/root"),
    capture_output=True, text=True)
check("adv-v6-6a rollback refuses when immutable prev image absent",
      p.returncode != 0 and "immutable image" in (p.stdout + p.stderr), p.stdout[-100:])
check("adv-v6-6b failed rollback did not relink state",
      open(SB + "/root/current.sha").read().strip() == Bv, open(SB + "/root/current.sha").read().strip()[:8])

print(f"\n{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
