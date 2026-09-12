import json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA="/tmp/barsdata2"
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
# mock is a non-allowlisted host here -> treated as PAID -> must fail closed
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="t",
           GROQ_API_TOKEN="fake", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1")
srv = subprocess.Popen([sys.executable,"server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars3.log","w"), stderr=subprocess.STDOUT)
def post(path, body):
    r = urllib.request.Request("http://127.0.0.1:4321"+path, data=json.dumps(body).encode(),
        headers={"Authorization":"Bearer t","content-type":"application/json"})
    try:
        with urllib.request.urlopen(r, timeout=15) as resp: return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError: return {}

def req(body, confirmed=True):
    hdrs = {"Authorization":"Bearer t","content-type":"application/json"}
    if confirmed:
        cj = post("/api/confirmations", {"action":"chat.exec","payload":body,"recipient":"/chat"})
        hdrs["X-BARS-Confirmation"] = cj.get("id","")
    r = urllib.request.Request("http://127.0.0.1:4321/chat", data=json.dumps(body).encode(),
        headers=hdrs)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp: return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
for _ in range(40):
    try:
        req({"text":"ok"}, confirmed=False); break
    except Exception: time.sleep(0.25)
s,b = req({"text":"what time is it in Seoul?"})
ok1 = s==500 and "fail-closed" in str(b.get("error",""))
print("PASS paid route fail-closed" if ok1 else f"FAIL {s} {b}")
# budget path: enable paid with tiny budget -> first call ok, then exhaust
srv.send_signal(15); srv.wait(timeout=10)
env2 = dict(env, BARS_ALLOW_PAID="1", BARS_PAID_TOKEN_BUDGET="3800")
srv2 = subprocess.Popen([sys.executable,"server.py"], cwd=ROOT, env=env2,
                        stdout=open("/tmp/bars4.log","w"), stderr=subprocess.STDOUT)
for _ in range(40):
    try: req({"text":"ok"}); break
    except Exception: time.sleep(0.25)
s1,b1 = req({"text":"what time is it in Seoul?"})
s2,b2 = req({"text":"what time is it in Tokyo?"})
print("call1", s1, str(b1)[:100])
print("call2", s2, str(b2)[:140])
ok2 = s1==200 and s2==500 and "budget" in str(b2.get("error",""))
print("PASS budget hard cap (reserve-before-spend, settle actuals)" if ok2 else "FAIL budget cap")
# duplex: wrong token 401, right token works (token file in DATA)
tok = json.load(open(os.path.join(DATA,"bars-duplex.json")))["token"]
def dup(t):
    r = urllib.request.Request("http://127.0.0.1:4323/v1/chat/completions",
        data=json.dumps({"messages":[{"role":"user","content":"hi"}]}).encode(),
        headers={"Authorization":f"Bearer {t}","content-type":"application/json"})
    try:
        with urllib.request.urlopen(r, timeout=15) as resp: return resp.status
    except urllib.error.HTTPError as e: return e.code
print("PASS duplex auth" if (dup("nope")==401 and dup(tok)==200) else "FAIL duplex auth")
srv2.send_signal(15); srv2.wait(timeout=10); mock.kill()

# under-budget: a call whose reservation exceeds the daily cap is blocked BEFORE spending
srv2.send_signal(15); srv2.wait(timeout=10)
env3 = dict(env, BARS_ALLOW_PAID="1", BARS_PAID_TOKEN_BUDGET="10")
srv3 = subprocess.Popen([sys.executable,"server.py"], cwd=ROOT, env=env3,
                        stdout=open("/tmp/bars5.log","w"), stderr=subprocess.STDOUT)
for _ in range(40):
    try: req({"text":"ok"}); break
    except Exception: time.sleep(0.25)
s3,b3 = req({"text":"what time is it in Seoul?"})
ok3 = s3==500 and "budget" in str(b3.get("error",""))
print("PASS under-budget first call blocked pre-spend" if ok3 else f"FAIL under-budget {s3} {b3}")
srv3.send_signal(15); srv3.wait(timeout=10)
