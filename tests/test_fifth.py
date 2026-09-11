# BARS adversarial suite v4 - fifth-review items. Versioned: adv-v4-<n>.
import json, os, shutil, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bars_security as sec

passed, failed = [], []
def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# adv-v4-1: multiprocess appends -> one verified chain, unique seqs (reload-under-lock)
RD = "/tmp/v4-rec"; shutil.rmtree(RD, ignore_errors=True); os.makedirs(RD)
kid = os.path.join(RD, ".k")
led = os.path.join(RD, "receipts.jsonl")
worker = ("import sys;sys.path.insert(0,%r);import bars_security as s;"
          "r=s.ReceiptLedger(%r,%r);"
          "[r.append({'kind':'mp','i':i}) for i in range(5)]" % (ROOT, led, kid))
procs = [subprocess.Popen([sys.executable, "-c", worker]) for _ in range(3)]
rc = [p.wait() for p in procs]
check("adv-v4-1a all processes appended cleanly", rc == [0, 0, 0], str(rc))
r = sec.ReceiptLedger(led, kid)
lines = open(led).read().strip().splitlines()
seqs = sorted(json.loads(l)["seq"] for l in lines)
check("adv-v4-1b 15 unique sequential seqs", len(lines) == 15 and seqs == list(range(1, 16)), str(seqs)[:60])
ok, prob = r.verify()
check("adv-v4-1c cross-process chain verifies", ok, str(prob))

# adv-v4-2: anchor HMAC tamper -> fail-closed (append refused)
shutil.rmtree(RD); os.makedirs(RD)
r = sec.ReceiptLedger(led, kid); r.append({"kind": "x", "i": 1})
a = json.load(open(led + ".anchor"))
a["_h"] = "0" * 64   # forged anchor
json.dump(a, open(led + ".anchor", "w"))
r2 = sec.ReceiptLedger(led, kid)
f = r2.status().get("startup_findings", [])
check("adv-v4-2a forged anchor surfaced", any("anchor" in x.lower() for x in f), str(f)[:120])
r2.append({"kind": "y"})
check("adv-v4-2b append refused while fail-closed", r2.write_failures > 0 and "fail-closed" in str(r2.last_error), str(r2.last_error)[:80])

# adv-v4-3: missing anchor on a non-empty ledger -> fail-closed
shutil.rmtree(RD); os.makedirs(RD)
r = sec.ReceiptLedger(led, kid); r.append({"kind": "x", "i": 1})
os.remove(led + ".anchor")
r3 = sec.ReceiptLedger(led, kid)
check("adv-v4-3 missing anchor fail-closed", r3._broken and any("anchor missing" in x for x in r3.status()["startup_findings"]), str(r3.status()["startup_findings"])[:120])

# adv-v4-4: anchor outside the writable data domain via env override
shutil.rmtree(RD); os.makedirs(RD); os.makedirs("/tmp/v4-outside", exist_ok=True)
os.environ["BARS_RECEIPT_ANCHOR_PATH"] = "/tmp/v4-outside/receipt.anchor"
r4 = sec.ReceiptLedger(led, kid); r4.append({"kind": "z", "i": 1})
check("adv-v4-4 anchor stored outside data dir",
      os.path.exists("/tmp/v4-outside/receipt.anchor") and not os.path.exists(led + ".anchor"))
del os.environ["BARS_RECEIPT_ANCHOR_PATH"]

# adv-v4-5 CRITICAL: Anthropic key is NEVER sent to OpenRouter on routed-provider failure
LD = "/tmp/v4-leak"; shutil.rmtree(LD, ignore_errors=True); os.makedirs(LD)
json.dump({"model": {"api_key": "sk-ant-native", "model": "claude-x"}}, open(os.path.join(LD, "config.json"), "w"))
os.environ.update(BARS_CONFIG=os.path.join(LD, "config.json"), BARS_DATA_DIR=os.path.join(LD, "data"),
                  AI_GATEWAY_API_KEY="gwfake", BARS_NO_BROWSER="1", BARS_DISABLE_HANDS="1", BARS_OPERATOR_TOKEN="v4tok", BARS_FREE_PROVIDERS="ai-gateway.vercel.sh,api.groq.com")
import importlib
import server
importlib.reload(server)
check("adv-v4-5a native key bound to api.anthropic.com",
      server._KEY_HOSTS.get("sk-ant-native") == "api.anthropic.com", str(server._KEY_HOSTS))
check("adv-v4-5b gateway key bound to gateway host",
      server._KEY_HOSTS.get("gwfake") == "ai-gateway.vercel.sh", str(server._KEY_HOSTS))
try:
    server._enforce_key_host("sk-ant-native", "https://openrouter.ai/api/v1")
    check("adv-v4-5c native key to openrouter refused", False)
except RuntimeError as e:
    check("adv-v4-5c native key to openrouter refused", "key-host binding" in str(e), str(e)[:80])
import bars_router
bars_router.bars_route = lambda um, available=None: {"model": {
    "model": "gpt-x", "base_url": "https://ai-gateway.vercel.sh/v1", "max_tokens": 64,
    "api_key_env": "AI_GATEWAY_API_KEY", "lane": "gateway", "routing": "test"}}
calls = []
def boom(req, **kw):
    calls.append(req.full_url)
    raise RuntimeError("gateway 401")
server.urllib.request.urlopen = boom
try:
    server.anthropic_chat("sys", [{"role": "user", "content": "hi"}], user_message="hi")
    check("adv-v4-5d fallback raises instead of leaking", False)
except RuntimeError as e:
    check("adv-v4-5d fallback raises instead of leaking",
          "fallback refused" in str(e) and "key-host binding" in str(e), str(e)[:110])
check("adv-v4-5e NO request ever constructed to openrouter",
      len(calls) == 1 and "ai-gateway.vercel.sh" in calls[0]
      and not any("openrouter" in u for u in calls), str(calls))

# adv-v4-6: XFF trusted only from loopback proxy
class FakeH:
    client_address = ("8.8.8.8", 1)
    headers = {"X-Forwarded-For": "203.0.113.9"}
    TRUSTED_PROXIES = frozenset({"127.0.0.1", "::1"})
check("adv-v4-6 non-loopback peer cannot spoof XFF",
      server.Handler._client_ip(FakeH()) == "8.8.8.8")
FakeH.client_address = ("127.0.0.1", 1)
check("adv-v4-6b loopback proxy peer honors XFF",
      server.Handler._client_ip(FakeH()) == "203.0.113.9")

print(f"\n{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
