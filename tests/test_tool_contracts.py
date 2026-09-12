# BARS tool contracts suite - native function calling, schema registry, enforcement.
import json, os, shutil, subprocess, sys, time
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# ---------- unit level: the registry seam
import tool_contracts as tc

schemas = tc.model_schemas()
check("tc-u1 four chat tools exposed", {s["function"]["name"] for s in schemas} ==
      {"deploy_mission", "propose_action", "request_takeover", "manage_tool"},
      str([s["function"]["name"] for s in schemas]))
blob = json.dumps(schemas)
check("tc-u2 host internals never leak into model payload",
      all(k not in blob for k in ("marker", "side_effect", "followups", '"output"')),
      blob[:160])
check("tc-u3 every tool declares a mandatory output schema",
      all("output" in s and "required" in s["output"] for s in tc.TOOLS.values()))

a = tc.validate_args("deploy_mission", {"brief": "research x", "agent": "KIPP", "evil": True})
check("tc-u4 args allowlisted (unknown keys dropped)",
      a == {"brief": "research x", "agent": "KIPP"}, str(a))
check("tc-u5 missing required arg rejected",
      tc.validate_args("deploy_mission", {"agent": "KIPP"}) is None)
check("tc-u6 wrong type rejected",
      tc.validate_args("deploy_mission", {"brief": 42}) is None)
check("tc-u7 unknown tool rejected", tc.validate_args("delete_everything", {}) is None)
check("tc-u8 unparseable arguments rejected",
      tc.validate_args("deploy_mission", "{not json") is None)

ok, errs = tc.validate_result("deploy_mission", {"proposed": True, "brief": "x", "agent": None})
check("tc-u9 well-formed proposal passes output schema", ok, str(errs))
ok, errs = tc.validate_result("deploy_mission", {"brief": "x"})
check("tc-u10 proposal missing required field fails output schema", not ok, str(errs))
ok, errs = tc.validate_result("manage_tool", {"proposed": True, "op": "add", "id": "sentry"})
check("tc-u11 manage_tool output validated", ok, str(errs))

# ---------- live server: native dispatch end to end
DATA = "/tmp/tools-data"
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
mock = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "mock_tools_provider.py")],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="tctok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app",
           GROQ_API_TOKEN="fake-token", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_GIT_SHA="tcsha1", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
           BARS_PORT="4332")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_tools.log", "w"), stderr=subprocess.STDOUT)

B = "http://127.0.0.1:4332"
TOK = {"Authorization": "Bearer tctok"}
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
check("tc-s0 server up", s == 200, str(s))

TOOLS_FILE = os.path.join(DATA, "bars-tools.json")
def installed_tools():
    try: return (json.load(open(TOOLS_FILE)) or {}).get("installed", {})
    except Exception: return {}

s, h, b = req("POST", "/chat", {"text": "MOCKTOOL deploy"}, TOK)
check("tc-s1 native deploy call -> mission proposal, no marker text in reply",
      s == 200 and (b.get("deployed") or {}).get("proposed") is True
      and b["deployed"]["brief"] == "research rival merch pricing"
      and b["deployed"]["agent"] == "KIPP"
      and "[DEPLOY" not in b.get("reply", ""), str(b)[:220])
check("tc-s2 no mission started without confirmation",
      not __import__("os").listdir(os.path.join(DATA, "missions")) if os.path.exists(os.path.join(DATA, "missions")) else True, "")

s, h, b = req("POST", "/chat", {"text": "MOCKTOOL act"}, TOK)
check("tc-s3 native act call -> pending action only",
      s == 200 and (b.get("pending") or {}).get("desc") == "post the announcement"
      and b["pending"].get("id"), str(b)[:200])

baseline = installed_tools()
s, h, b = req("POST", "/chat", {"text": "MOCKTOOL tooladd"}, TOK)
check("tc-s4 native manage_tool call -> proposed add, no mutation",
      s == 200 and (b.get("tool") or {}).get("proposed") is True
      and b["tool"]["op"] == "add" and b["tool"]["id"] == "sentry"
      and installed_tools() == baseline, str(b)[:200])

s, h, b = req("POST", "/chat", {"text": "MOCKTOOL badargs"}, TOK)
check("tc-s5 malformed call args -> no proposal ships",
      s == 200 and not b.get("deployed") and not b.get("pending") and not b.get("tool")
      and b.get("reply"), str(b)[:200])

s, h, b = req("POST", "/chat", {"text": "MOCKTOOL badtool"}, TOK)
check("tc-s6 unknown tool name -> no proposal ships",
      s == 200 and not b.get("deployed") and not b.get("pending") and not b.get("tool"),
      str(b)[:200])

s, h, b = req("POST", "/chat", {"text": "MOCKTOOL notools"}, TOK)
check("tc-s7 plain completion with tools available ships as chat",
      s == 200 and b.get("reply") == "plain answer, no call needed"
      and not b.get("deployed"), str(b)[:160])

# marker fallback still works when the provider speaks tags
s, h, b = req("POST", "/chat", {"text": "MOCKSAY queued\n[ACT: post the announcement]"}, TOK)
check("tc-s8 regex marker fallback unchanged",
      s == 200 and (b.get("pending") or {}).get("desc") == "post the announcement",
      str(b)[:200])

srv.terminate(); mock.terminate()
print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILURES:", failed); sys.exit(1)
