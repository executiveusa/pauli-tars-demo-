# BARS memory v2 suite - structured store, provenance, retrieval, transcripts.
import json, os, shutil, subprocess, sys, time
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# ---------- unit level: memory_store directly
import memory_store as memv2
U = "/tmp/memv2-unit"
shutil.rmtree(U, ignore_errors=True); os.makedirs(U)
memv2.init(U)

bad = None
try:
    memv2.add_fact("something", provenance="guessed")
except ValueError as e:
    bad = str(e)
check("mem2-u1 invalid provenance refused", bad is not None, str(bad))

memv2.add_fact("the Commander's studio is in Richmond", provenance="stated")
time.sleep(0.02)
memv2.add_fact("pepperoni is the usual pizza order", provenance="observed")
time.sleep(0.02)
memv2.add_fact("he probably likes vinyl", provenance="inferred")

recs = memv2.recall("where is the studio", limit=3)
check("mem2-u2 keyword-relevant fact beats newer irrelevant facts",
      len(recs) >= 1 and "Richmond" in recs[0]["text"], str([r["text"][:30] for r in recs]))
check("mem2-u3 provenance tags survive retrieval",
      recs and recs[0]["prov"] == "stated", str(recs[:1]))
block = memv2.facts_block("studio")
check("mem2-u4 prompt block carries visible provenance tag",
      "[stated]" in block and "Richmond" in block, block[:120])
recs2 = memv2.recall("", limit=2)
check("mem2-u5 empty query falls back to recency order",
      len(recs2) == 2 and "vinyl" in recs2[0]["text"], str([r["text"][:24] for r in recs2]))

os.makedirs(U, exist_ok=True)
flat = os.path.join(U, "flat.md")
open(flat, "w").write("- [2026-09-01] the Commander goes by Bambu\n- [2026-09-02] keep deploys free\n")
n1 = memv2.migrate_flat(flat)
n2 = memv2.migrate_flat(flat)
migrated = [r for r in memv2.load_facts() if r.get("src") == "migration"]
check("mem2-u6 flat migration imports as stated, idempotent",
      n1 == 2 and n2 == 0 and len(migrated) == 2
      and all(r["prov"] == "stated" for r in migrated),
      f"first={n1} second={n2} migrated={len(migrated)}")

memv2.append_turn("s1", "user", "first question")
memv2.append_turn("s1", "assistant", "first answer")
memv2.append_turn("s1", "user", "second question")
turns = memv2.transcript("s1", 16)
check("mem2-u7 transcript persists turns in order",
      [t["role"] for t in turns] == ["user", "assistant", "user"], str(turns)[:120])
check("mem2-u8 sessions listed", "s1" in memv2.sessions())
bad = None
try:
    memv2.append_turn("s1", "system", "nope")
except ValueError as e:
    bad = str(e)
check("mem2-u9 non-chat roles refused", bad is not None, str(bad))

# ---------- live server: endpoints + /chat wiring
DATA = "/tmp/memv2-data"
shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
open(os.path.join(DATA, "bars-memory.md"), "w").write(
    "- [2026-09-01] legacy fact from the flat file\n")

# mock provider copy that reports how many messages it received
mocksrc = open(os.path.join(ROOT, "tests", "mock_provider.py")).read()
anchor = ('        if user.startswith("MOCKSAY "):\n'
          '            txt = user[len("MOCKSAY "):]          # verbatim: marker-injection tests\n'
          '        else:\n'
          '            txt = f"MOCK-REPLY[{model}]: " + user[:60]')
assert anchor in mocksrc, "mock anchor drifted - update this patch"
mocksrc = mocksrc.replace(anchor, anchor +
    '\n        txt += f" [msgs={len(data.get(\'messages\', []))}]"')
open("/tmp/memv2_mock.py", "w").write(mocksrc)
mock = subprocess.Popen([sys.executable, "/tmp/memv2_mock.py"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, BARS_DATA_DIR=DATA, BARS_OPERATOR_TOKEN="memtok",
           BARS_ALLOWED_ORIGINS="https://barsdemo.netlify.app",
           GROQ_API_TOKEN="fake-token", BARS_BASE_URL="http://127.0.0.1:9999/v1",
           BARS_GROQ_BASE="http://127.0.0.1:9999/v1",
           BARS_FREE_PROVIDERS="127.0.0.1,api.groq.com",
           BARS_GIT_SHA="memsha1", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1",
           BARS_PORT="4330")
srv = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                       stdout=open("/tmp/bars_memv2.log", "w"), stderr=subprocess.STDOUT)

B = "http://127.0.0.1:4330"
TOK = {"Authorization": "Bearer memtok"}
def req(method, path, body=None, headers=None):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h["content-type"] = "application/json"
    r = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
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
check("mem2-s0 server up", s == 200, str(s))

s, h, b = req("GET", "/api/memory/recall")
check("mem2-s1 recall requires auth", s == 401, str(s))
s, h, b = req("GET", "/api/memory/recall?q=legacy", headers=TOK)
check("mem2-s2 flat file migrated at startup and retrievable",
      s == 200 and any("legacy fact" in f["text"] for f in b.get("facts", [])),
      str(b)[:200])
s, h, b = req("GET", "/api/memory/recall?q=legacy", headers=TOK)
facts_before = {f["text"]: f.get("hits", 0) for f in b.get("facts", [])}
s, h, b = req("GET", "/api/memory/recall?q=legacy", headers=TOK)
facts_after = {f["text"]: f.get("hits", 0) for f in b.get("facts", [])}
check("mem2-s3 read endpoint does not bump hit counters", facts_before == facts_after,
      f"{facts_before} -> {facts_after}")

s, h, b = req("POST", "/remember", {"text": "the vault door code rotates weekly"}, TOK)
check("mem2-s4 remember ok", s == 200 and b.get("ok"), str(b)[:120])
s, h, b = req("POST", "/remember", {"text": "x", "provenance": "guessed"}, TOK)
check("mem2-s5 invalid provenance 400", s == 400, str(s))
s, h, b = req("POST", "/remember",
              {"text": "the merch drop is probably Friday", "provenance": "inferred"}, TOK)
check("mem2-s6 inferred provenance accepted", s == 200, str(s))
s, h, b = req("GET", "/api/memory/recall?q=merch+drop", headers=TOK)
check("mem2-s7 inferred fact retrievable with its tag",
      s == 200 and any(f["prov"] == "inferred" for f in b.get("facts", [])), str(b)[:200])
mem = open(os.path.join(DATA, "bars-memory.md")).read()
check("mem2-s8 flat mirror still written for legacy readers",
      "vault door code rotates weekly" in mem)

# /chat: server-side transcript owns the history
s, h, b = req("POST", "/chat", {"text": "hello session one", "session": "t-one"}, TOK)
check("mem2-s9 chat one ok", s == 200 and "msgs=2" in str(b.get("reply")), str(b.get("reply"))[:120])
s, h, b = req("POST", "/chat", {"text": "follow up without client history", "session": "t-one"}, TOK)
check("mem2-s10 second chat carries server-side history (no client history sent)",
      s == 200 and "msgs=4" in str(b.get("reply")), str(b.get("reply"))[:120])
s, h, b = req("GET", "/api/memory/transcript?session=t-one", headers=TOK)
check("mem2-s11 transcript endpoint returns all four turns in order",
      s == 200 and [t["role"] for t in b.get("turns", [])] ==
      ["user", "assistant", "user", "assistant"], str(b)[:240])
check("mem2-s12 session appears in listing", "t-one" in b.get("sessions", []))

s, h, b = req("POST", "/chat", {"text": "third", "session": "t-one",
                                "history": [{"role": "user", "content": "ancient client turn"}]}, TOK)
check("mem2-s13 client history cannot resurrect turns the server already owns",
      s == 200 and "msgs=6" in str(b.get("reply")), str(b.get("reply"))[:120])

s, h, b = req("POST", "/chat", {"text": "fresh session", "session": "t-two",
                                "history": [{"role": "user", "content": "old client turn"},
                                            {"role": "assistant", "content": "old client answer"}]}, TOK)
check("mem2-s14 first contact adopts client history into transcript",
      s == 200 and "msgs=4" in str(b.get("reply")), str(b.get("reply"))[:120])
s, h, b = req("GET", "/api/memory/transcript?session=t-two", headers=TOK)
check("mem2-s15 adopted turns persisted server-side",
      s == 200 and any("old client turn" in t["content"] for t in b.get("turns", [])),
      str(b)[:240])

srv.terminate(); mock.terminate()
print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILURES:", failed); sys.exit(1)
