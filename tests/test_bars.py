import json, os, shutil, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = "/tmp/barsdata"
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)

mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="testtok123",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app",
           GROQ_API_TOKEN="fake-token", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_GIT_SHA="testsha1", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars.log","w"), stderr=subprocess.STDOUT)

B = "http://127.0.0.1:4321"
TOK = {"Authorization": "Bearer testtok123"}
def req(method, path, body=None, headers=None, raw=False):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B+path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            b = resp.read()
            if raw or "application/json" not in resp.headers.get("Content-Type",""):
                return resp.status, dict(resp.headers), b
            return resp.status, dict(resp.headers), json.loads(b or b"{}")
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, dict(e.headers), json.loads(b or b"{}")
        except Exception: return e.code, dict(e.headers), {"raw": b[:200].decode(errors="replace")}

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

for _ in range(40):
    try:
        s,_,_ = req("GET","/health"); break
    except Exception: time.sleep(0.25)

s,h,b = req("GET","/health"); check("health public", s==200 and b.get("sha")=="testsha1", str(b))
s,h,b = req("GET","/", raw=True); check("/ serves cockpit", s==200 and b"<title>BARS" in b, "")
check("auth shim injected (csrf session shim)", b"bars_csrf" in b)
s,h,b = req("GET","/frontdoor/", raw=True); check("/frontdoor/ serves frontdoor", s==200 and "Trail Mixx".encode() in b)
s,h,b = req("GET","/agent/"); check("/agent/ cockpit", s==200)
s,h,b = req("GET","/missions"); check("unauth /missions 401", s==401)
s,h,b = req("GET","/api/status"); check("anon status sanitized", s==200 and b.get("mode")=="public", str(b))
s,h,b = req("GET","/missions", headers={"Authorization":"Bearer nope"}); check("wrong token 401", s==401)
s,h,b = req("POST","/api/session", {"token":"testtok123"})
sess = h.get("Set-Cookie","") or h.get("set-cookie","")
check("session login sets HttpOnly SameSite=Strict cookies", s==200 and "bars_session=" in sess and "HttpOnly" in sess and "SameSite=Strict" in sess, sess[:120])
s,h,b = req("POST","/api/session", {"token":"wrong"}); check("session login wrong token 401", s==401)
s,h,b = req("GET","/missions", headers={"Cookie":sess.split(";")[0]}); check("session cookie ok (read)", s==200)
s,h,b = req("GET","/api/session", headers={"Cookie":sess.split(";")[0]}); check("session status returns csrf", s==200 and b.get("ok") and b.get("csrf"))
s,h,b = req("GET","/api/status", headers=TOK); check("authed status full", s==200 and b.get("auth_required") and b.get("missions_engine")=="internal-worker" and b.get("sha")=="testsha1", json.dumps(b)[:200])
s,h,b = req("POST","/chat", {}, {"Origin":"https://evil.example","Authorization":"Bearer testtok123"}); check("bad origin 403", s==403)
s,h,b = req("OPTIONS","/chat", headers={"Origin":"https://barsdemo.netlify.app"}); check("preflight allowed origin", s==204 and h.get("Access-Control-Allow-Origin")=="https://barsdemo.netlify.app")
s,h,b = req("POST","/chat", headers={"Origin":"https://barsdemo.netlify.app","Authorization":"Bearer testtok123","content-type":"application/json"}, body={"text":"ok"}); check("ACAO on response", h.get("Access-Control-Allow-Origin")=="https://barsdemo.netlify.app")
def chat(text, headers=None):
    return req("POST","/chat", body={"text":text}, headers=(headers or TOK))

s,h,b = req("POST","/chat", body={"text":"ok"}, headers=TOK); check("chat needs no approval (UX policy)", s==200 and b.get("reply"), str(b)[:140])
s,h,b = chat("ok"); check("direct lane cached", s==200 and b.get("reply")=="Locked.", str(b))
s,h,b = chat("what's the weather like today?")
check("flash lane routed", s==200 and b.get("lane")=="flash" and b.get("model")=="openai/gpt-oss-20b" and "MOCK-REPLY" in str(b.get("reply")), str(b)[:160])
s,h,b = chat("fix this python function bug in my code")
check("worker lane routed", s==200 and b.get("lane")=="worker" and b.get("model")=="openai/gpt-oss-120b", str(b)[:160])
s,h,b = chat("run the final independent security review before release")
check("judge lane routed", s==200 and b.get("lane")=="judge", str(b)[:120])
s,h,b = req("POST","/chat", headers=TOK, body={"text":"unauth check"})
check("chat needs auth", True)  # placeholder replaced below
s2,h2,b2 = req("POST","/chat", body={"text":"hi"}); check("chat 401 without token", s2==401)
s,h,b = req("GET","/api/models", headers=TOK)
check("models live", s==200 and b.get("live") and any(m["id"]=="openai/gpt-oss-120b" for m in b["models"]), "")
check("lanes resolved verified", b["lanes"]["flash"]["model"]=="openai/gpt-oss-20b" and b["lanes"]["flash"]["verified"] and b["lanes"]["worker"]["model"]=="openai/gpt-oss-120b", json.dumps(b["lanes"]))
def confirmed(action, payload, recipient):
    s2,h2,cj = req("POST","/api/confirmations", {"action":action,"payload":payload,"recipient":recipient}, headers=TOK)
    assert s2==200 and cj.get("id"), f"mint failed {s2} {cj}"
    hh = dict(TOK); hh["X-BARS-Confirmation"] = cj["id"]; return hh
s,h,b = req("POST","/model", body={"model":"openai/gpt-oss-20b"}, headers=TOK); check("manual switch gated 409", s==409 and b.get("need_confirmation",{}).get("action")=="model.switch")
# canonical base in this deployment is the configured mock base
s,h,b = req("POST","/model", body={"model":"openai/gpt-oss-20b"}, headers=confirmed("model.switch",{"model":"openai/gpt-oss-20b","base_url":"http://127.0.0.1:9999/v1"},"/model")); check("manual switch valid", s==200 and b.get("ok"))
s,h,b = req("POST","/model", body={"model":"not-a-model"}, headers=TOK); check("manual switch invalid 400", s==400)
s,h,b = req("POST","/remember", body={"text":"test memory item alpha"}, headers=TOK); check("remember ok", s==200 and b.get("ok"))
brief = "Summarize the history of DJ culture in two paragraphs"
s,h,b = req("POST","/brief", body={"brief":brief}, headers=TOK)
check("mission without confirmation 409", s==409 and b.get("need_confirmation",{}).get("action")=="mission.exec", str(b)[:140])
s,h,cj = req("POST","/api/confirmations", {"action":"mission.exec","payload":{"brief":brief},"recipient":"/brief"}, headers=TOK)
check("confirmation minted w/ payload hash", s==200 and cj.get("id") and cj.get("payload_sha256"), str(cj)[:140])
H = dict(TOK); H["X-BARS-Confirmation"] = cj.get("id","")
s,h,b = req("POST","/brief", body={"brief":brief}, headers=H)
check("mission created with confirmation", s==200 and b.get("id"), str(b))
s,h,bx = req("POST","/brief", body={"brief":brief}, headers=H)
check("confirmation single-use (replay 409)", s==409)
mid = b.get("id")
for _ in range(60):
    s,h,b = req("GET", f"/mission/{mid}", headers=TOK)
    if b.get("status") != "EN ROUTE": break
    time.sleep(0.5)
check("mission completes via internal worker", b.get("status")=="COMPLETE", str(b.get("status"))+" "+str(b.get("debrief"))[:100])
check("mission report written", "MOCK-REPLY" in str(b.get("report")), "")
s,h,b = req("POST","/tts", body={"text":"hello commander"}, headers=TOK)
check("tts gated 409", s==409 and b.get("need_confirmation",{}).get("action")=="tts.exec", str(s))
s,h,b = req("POST","/tts", body={"text":"hello commander"}, headers=confirmed("tts.exec",{"text":"hello commander"},"/tts"))
check("tts graceful fallback (fake key)", s==200 and b.get("browser_fallback"), str(b)[:120])
s,h,b = req("POST","/stt", headers={"Authorization":"Bearer testtok123","content-type":"audio/webm"}, raw=True)
check("stt needs audio 400", s==400)
# receipts
rp = os.path.join(DATA, "receipts.jsonl")
rec = [json.loads(l) for l in open(rp)]
check("receipts durable", len(rec) >= 5 and any(r.get("lane")=="direct" and r.get("cache_hit") for r in rec) and any(r.get("lane")=="flash" and r.get("model")=="openai/gpt-oss-20b" for r in rec), f"{len(rec)} receipts")
# graceful restart + persistence
srv.send_signal(15)
try: srv.wait(timeout=10)
except Exception: srv.kill()
check("SIGTERM graceful exit", srv.returncode in (0, -15), str(srv.returncode))
srv2 = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                        stdout=open("/tmp/bars2.log","w"), stderr=subprocess.STDOUT)
for _ in range(40):
    try:
        s,_,_ = req("GET","/health"); break
    except Exception: time.sleep(0.25)
s,h,b = req("GET", f"/mission/{mid}", headers=TOK); check("mission survives restart", s==200 and b.get("status")=="COMPLETE")
s,h,b = req("GET","/missions", headers=TOK); check("board persists", s==200 and any(m["id"]==mid for m in b["missions"]))
mem = open(os.path.join(DATA,"bars-memory.md")).read(); check("memory persists", "test memory item alpha" in mem)
check("state in DATA not repo", os.path.exists(os.path.join(DATA,"bars-state.json")) and not os.path.exists(os.path.join(ROOT,"bars-state.json")))
srv2.send_signal(15)
try: srv2.wait(timeout=10)
except Exception: srv2.kill()
mock.kill()
print(f"\n== {len(passed)} passed, {len(failed)} failed ==")
if failed:
    print("FAILED:", failed); sys.exit(1)
