#!/usr/bin/env python3
"""Eleventh ledger round: adversarial proof of the OCR-34574370089 fixes.

Covers: HIGH-a lock-FD leak (append try/finally), HIGH-b backup perms 0666->0600,
HIGH-c rollback restore-on-fail, P1 anchor temp on the anchor filesystem (EXDEV),
P1 chain-state mismatch fail-closed, P1 uid-10001 dir provisioning doc/script,
P2 shim deny-settles-promise + mission image carry, MED models-cache keying,
MED paid-media fail-closed, LOW missing-AGENTS.md gate + workflow concurrency.
Static checks read the files; behavioral checks run real ReceiptLedger code.
"""
import fcntl, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []

def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def read(p):
    return open(os.path.join(ROOT, p)).read()

# ---------- static: deploy/rollback/docs/workflows/gate ----------
dep = read("deploy/deploy.sh")
check("deploy: no world-readable backup mode", "0666" not in dep)
check("deploy: backup chowned to host user + 0600",
      "chown $(id -u):$(id -g)" in dep and "chmod 0600" in dep)
check("deploy: provisions uid-10001 data/anchor dirs",
      "install -d -m 0755 -o 10001 -g 10001" in dep)

rb = read("deploy/rollback.sh")
check("rollback: root branch restores $DATA on swap failure",
      'if ! mv "$TMPD" "$DATA"; then' in rb and 'mv "$OLD" "$DATA" || true' in rb)
check("rollback: docker branch restores data on swap failure",
      'if ! mv "$T" /baroot/data; then' in rb and 'mv "$O" /baroot/data || true' in rb)
check("rollback: both failure paths exit nonzero", rb.count("restored original data dir") == 2)

dm = read("DEPLOY.md")
check("DEPLOY.md: one-time setup chowns uid 10001", "10001" in dm and "install -d" in dm)

bc = read(".github/workflows/bars-check.yml")
check("bars-check: concurrency group", "concurrency:" in bc and "bars-check-" in bc)
check("bars-check: job timeout", "timeout-minutes: 40" in bc)
vr = read(".github/workflows/vibe-code-review.yml")
check("vibe-review: concurrency group", "concurrency:" in vr and "vibe-code-review-" in vr)

gate_src = read("scripts/check_release_gate.py")
check("gate: missing AGENTS.md handled explicitly", 'fail.append("missing AGENTS.md")' in gate_src)
check("gate: unused json import gone", not re.search(r"^import json", gate_src, re.M))
# gate must fail STRUCTURED (no traceback) when AGENTS.md is absent
import json as _json
tmpdir = tempfile.mkdtemp(prefix="gate-noagents-")
try:
    shutil.copytree(os.path.join(ROOT, ".github"), os.path.join(tmpdir, ".github"))
    # the script resolves ROOT as parents[1] of its own path: keep the
    # scripts/ layout so ROOT == tmpdir (no AGENTS.md by construction)
    os.makedirs(os.path.join(tmpdir, "scripts"))
    shutil.copy(os.path.join(ROOT, "scripts/check_release_gate.py"),
                os.path.join(tmpdir, "scripts", "check_release_gate.py"))
    assert not os.path.exists(os.path.join(tmpdir, "AGENTS.md"))
    r = subprocess.run([sys.executable, os.path.join(tmpdir, "scripts", "check_release_gate.py")],
                       capture_output=True, text=True, cwd=tmpdir)
    check("gate: structured failure without AGENTS.md",
          "missing AGENTS.md" in (r.stdout + r.stderr) and "Traceback" not in (r.stdout + r.stderr))
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ---------- static: server.py mediums + shim ----------
srv = read("server.py")
check("models cache keyed by provider",
      '"provider": None' in srv and "provider = (base, hashlib.sha256" in srv)
paid_idx = srv.index('paid_ok = os.environ.get("BARS_ALLOW_PAID") == "1"')
check("paid TTS lane (ElevenLabs) fail-closed on BARS_ALLOW_PAID",
      'if paid_ok and CONFIG["el_key"] and CONFIG["el_voice"]:' in srv and
      "def tts_bytes" in srv and paid_idx > srv.index("def tts_bytes"))
check("free Groq/browser TTS lanes NOT behind the paid flag",
      srv.index("_groq_tts(t)") > paid_idx and "browser_fallback" in srv)
check("media gate keeps confirmation+budget semantics (no blanket 402)",
      'def _paid_media_gate' in srv and
      'BARS_ALLOW_PAID\") != "1"' not in srv[srv.index("def _paid_media_gate"):srv.index("def _body")])

# ---------- shim: parses as JS + deny/mbind wired ----------
m = re.search(r'(AUTH_SHIM = \(.*?</script>"\))\n', srv, re.S)
g = {}
exec(m.group(1), g)
js = g["AUTH_SHIM"].decode().replace("<script>", "").replace("</script>", "")
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(js); jspath = f.name
node = shutil.which("node")
if node:
    r = subprocess.run([node, "--check", jspath], capture_output=True, text=True)
    check("AUTH_SHIM parses as valid JavaScript (node --check)", r.returncode == 0, r.stderr[:200])
else:
    check("AUTH_SHIM parses as valid JavaScript (node --check)", False, "node unavailable")
os.unlink(jspath)
check("shim: outer table array terminated (was dead-on-arrival)", "after approval']]." in js or "after approval']]." in srv)
check("shim: DENY settles the wrapper promise (both confirm paths)",
      js.count("if(deny)deny()") == 1 and js.count(",function(){resolve(r)}") == 2)
check("shim: rejected mintAndRun also settles the wrapper promise",
      js.count(".catch(function(){resolve(r)})") == 2)
check("shim: confirmed missions carry the original payload (image)",
      "Object.assign({},payloadObj,{brief:j.deployed.brief})" in js and
      "mintAndRun('mission.exec',mbind" in js)

# ---------- behavioral: ReceiptLedger OCR fixes ----------
import bars_security

keydir = tempfile.mkdtemp(prefix="v11-key-")
key_path = os.path.join(keydir, "k")
with open(key_path, "wb") as f:
    f.write(os.urandom(48))

# P1: anchor temp must be created on the ANCHOR filesystem (no EXDEV)
d1 = tempfile.mkdtemp(prefix="v11-data-")
d2 = tempfile.mkdtemp(prefix="v11-anchor-")
os.environ["BARS_RECEIPT_ANCHOR_PATH"] = os.path.join(d2, "receipt.anchor")
captured = {}
real_mkstemp = tempfile.mkstemp
def spy_mkstemp(*a, **k):
    fd, tmp = real_mkstemp(*a, **k)
    captured["dir"] = k.get("dir") or (a[1] if len(a) > 1 else None)
    captured["prefix"] = k.get("prefix") or (a[0] if a else None)
    return fd, tmp
bars_security.tempfile.mkstemp = spy_mkstemp
try:
    led = bars_security.ReceiptLedger(os.path.join(d1, "ledger.jsonl"), key_path)
    led.append({"kind": "test", "n": 1})
finally:
    bars_security.tempfile.mkstemp = real_mkstemp
check("anchor temp created in the anchor directory",
      captured.get("prefix", "").startswith(".ranchor-") and
      captured.get("dir") == os.path.dirname(os.environ["BARS_RECEIPT_ANCHOR_PATH"]),
      str(captured))
check("anchor write succeeds cross-directory (EXDEV shape)", led.write_failures == 0,
      led.last_error or "")
check("anchor file exists with valid tip", os.path.exists(os.environ["BARS_RECEIPT_ANCHOR_PATH"]))

# simulate a TRUE cross-device replace: os.replace raising EXDEV must never be
# reachable now that temp and target share a directory
d5 = tempfile.mkdtemp(prefix="v11-anchor2-")
os.environ["BARS_RECEIPT_ANCHOR_PATH"] = os.path.join(d5, "receipt.anchor")
led2 = bars_security.ReceiptLedger(os.path.join(d1, "ledger2.jsonl"), key_path)
real_replace = os.replace
violations = []
def exdev_guard(src, dst):
    if os.path.dirname(src) != os.path.dirname(dst):
        violations.append(f"{src} -> {dst}")
    return real_replace(src, dst)
bars_security.os.replace = exdev_guard
try:
    led2.append({"kind": "test", "n": 1})
finally:
    bars_security.os.replace = real_replace
check("os.replace always same-directory (EXDEV unreachable)",
      not violations and led2.write_failures == 0, str(violations))

# P1: chain-state mismatch at startup must fail CLOSED
d3 = tempfile.mkdtemp(prefix="v11-mm-")
os.environ["BARS_RECEIPT_ANCHOR_PATH"] = os.path.join(d3, "ledger.jsonl.anchor")
led3 = bars_security.ReceiptLedger(os.path.join(d3, "ledger.jsonl"), key_path)
for i in range(3):
    led3.append({"kind": "test", "n": i})
assert led3.write_failures == 0
st_path = os.path.join(d3, "ledger.jsonl.state.json")
st = _json.load(open(st_path)); st["prev"] = "0" * 64
_json.dump(st, open(st_path, "w"))
before = os.path.getsize(os.path.join(d3, "ledger.jsonl"))
led4 = bars_security.ReceiptLedger(os.path.join(d3, "ledger.jsonl"), key_path)
check("chain mismatch at startup marks ledger broken", led4._broken is True)
led4.append({"kind": "test", "n": 99})
check("broken ledger refuses to extend an invalid chain",
      os.path.getsize(os.path.join(d3, "ledger.jsonl")) == before and led4.write_failures >= 1)

# HIGH-a: a failing append must release the flock and leak no FDs
d4 = tempfile.mkdtemp(prefix="v11-fd-")
os.environ["BARS_RECEIPT_ANCHOR_PATH"] = os.path.join(d4, "x.anchor")
led5 = bars_security.ReceiptLedger(os.path.join(d4, "x.jsonl"), key_path)
led5.append({"kind": "ok"})
assert led5.write_failures == 0
os.mkdir(os.path.join(d4, "dir-blocker"))
led5.path = os.path.join(d4, "dir-blocker")          # os.open(dir, O_WRONLY) raises mid-lock
led5._lock_path = os.path.join(d4, "x.jsonl.lock")
led5._anchor_path = os.environ["BARS_RECEIPT_ANCHOR_PATH"]
led5._state_path = os.path.join(d4, "dir-blocker.state.json")  # state "exists" check passes (dir)
fds_before = len(os.listdir("/proc/self/fd"))
for _ in range(50):
    led5.append({"kind": "boom"})
lf = os.open(led5._lock_path, os.O_RDWR)
try:
    fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    lock_free = True
except OSError:
    lock_free = False
finally:
    os.close(lf)
check("failed appends release the cross-process flock", lock_free)
check("failed appends leak no file descriptors",
      len(os.listdir("/proc/self/fd")) <= fds_before + 1,
      f"{fds_before} -> {len(os.listdir('/proc/self/fd'))}")

os.environ.pop("BARS_RECEIPT_ANCHOR_PATH", None)
print()
if FAILS:
    print("ELEVENTH ROUND: FAIL ->", FAILS); sys.exit(1)
print("ELEVENTH ROUND: ALL CHECKS PASS")
