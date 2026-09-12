#!/usr/bin/env python3
"""
BARS — hip-hop culture agent (the bars guardian).
Standalone. Never touches brain-studio (Jarvis) or mission-control.

  python3 server.py   →  http://localhost:4321

Brief a mission → BARS executes it headless (draft-safe `claude -p`)
→ smooth spoken debrief when you return. Flavor and authenticity are dials.
"""
import base64, fcntl, hashlib, hmac, json, os, re, shutil, signal, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import hue
import bars_security as sec
if os.environ.get("BARS_DISABLE_HANDS") == "1":
    HANDS = None                # sovereign/headless deployments: no machine control
else:
    try:
        import hands as HANDS   # real-Mac takeover bay (soft — server runs without pyobjc)
    except Exception:
        HANDS = None

STATIC = os.path.join(ROOT, "static")
# Durable state lives in BARS_DATA_DIR (default: repo root for local runs; a
# mounted volume such as /data in the sovereign container) so container
# rebuilds never touch memory, missions, dials, tools, receipts, or the
# duplex token.
DATA = os.environ.get("BARS_DATA_DIR", ROOT)
try:
    os.makedirs(DATA, exist_ok=True)
except Exception:
    DATA = ROOT
MISSIONS_DIR = os.path.join(DATA, "missions")
WORKBENCH = os.path.join(DATA, "workbench")
BUILDS_DIR = os.path.join(DATA, "builds")
STATE_PATH = os.path.join(DATA, "bars-state.json")
MEMORY_PATH = os.path.join(DATA, "bars-memory.md")
DUPLEX_PATH = os.path.join(DATA, "bars-duplex.json")
TOOLS_PATH = os.path.join(DATA, "bars-tools.json")
RECEIPTS_PATH = os.path.join(DATA, "receipts.jsonl")
LEGACY_STATE_PATH = os.path.join(ROOT, "tars-state.json")
LEGACY_MEMORY_PATH = os.path.join(ROOT, "tars-memory.md")
LEGACY_DUPLEX_PATH = os.path.join(ROOT, "tars-duplex.json")
LEGACY_TOOLS_PATH = os.path.join(ROOT, "tars-tools.json")

def _read_path(primary, legacy):
    return primary if os.path.exists(primary) else (legacy if os.path.exists(legacy) else primary)

def _migrate_legacy_file(primary, legacy):
    """Copy legacy state once; never delete or overwrite the legacy file."""
    if os.path.exists(primary) or not os.path.exists(legacy):
        return
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".bars-migrate-", dir=DATA)
        os.close(fd)
        shutil.copyfile(legacy, tmp)
        os.replace(tmp, primary)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass

for _primary, _legacy in ((STATE_PATH, LEGACY_STATE_PATH),
                          (MEMORY_PATH, LEGACY_MEMORY_PATH),
                          (DUPLEX_PATH, LEGACY_DUPLEX_PATH)):
    _migrate_legacy_file(_primary, _legacy)

# ------------------------------------------------- structured memory v2
import memory_store as memv2
import tool_contracts
import verify
memv2.init(DATA)
memv2.migrate_flat(_read_path(MEMORY_PATH, LEGACY_MEMORY_PATH))
PORT = int(os.environ.get("BARS_PORT", "4321"))
DUPLEX_PORT = int(os.environ.get("BARS_DUPLEX_PORT", "4323"))
BIND = os.environ.get("BARS_BIND", "127.0.0.1")
INTERNAL_WORKER = os.environ.get("BARS_INTERNAL_WORKER", "1") != "0"
OPERATOR_TOKEN = os.environ.get("BARS_OPERATOR_TOKEN", "")
if not OPERATOR_TOKEN and os.environ.get("BARS_OPEN_LOCAL") != "1":
    raise SystemExit("[bars] FATAL: BARS_OPERATOR_TOKEN required (fail-closed). "
                     "Set BARS_OPEN_LOCAL=1 for local dev only.")
ALLOW_LOCAL_DEV = os.environ.get("BARS_ALLOW_LOCAL_DEV", "1") == "1"
try:
    ALLOWED_ORIGINS = sec.parse_origin_allowlist(
        os.environ.get("BARS_ALLOWED_ORIGINS", ""), ALLOW_LOCAL_DEV)
except sec.SecurityConfigError as e:
    raise SystemExit(f"[bars] FATAL security config: {e}")
def _read_sha():
    # image-baked provenance wins: /health must report the SHA the code was
    # built from, not a circular runtime env echo
    try:
        _sha_file = (os.environ.get("BARS_SHA_FILE")
                     if os.environ.get("BARS_TEST_MODE") == "1" else None)
        with open(_sha_file or os.path.join(ROOT, ".bars_sha")) as f:
            v = f.read().strip()
            if re.fullmatch(r"[0-9a-f]{40}", v):
                return v
    except Exception:
        pass
    return os.environ.get("BARS_GIT_SHA", "")
GIT_SHA = _read_sha()
PAID_MODE = os.environ.get("BARS_ALLOW_PAID", "").strip() == "1"
_COST_CAP = threading.local()   # per-request enforced cap from the shown bound
# ONE aggregate budget object per confirmed action, shared across the request
# thread and every worker thread the action spawns (missions, squad children,
# acts). Thread-safe; conservative: reserves estimate before the call, charges
# actuals after, fails closed when the shown aggregate bound would be exceeded.
MISSION_CAPS = {}
MISSION_CAPS_LOCK = threading.Lock()

def _cap_register(key, bound):
    with MISSION_CAPS_LOCK:
        MISSION_CAPS[key] = {"bound": int(bound or 0), "used": 0}

def _cap_reserve(key, est):
    """Atomically reserve est against the aggregate bound; fail closed."""
    if not key:
        return
    with MISSION_CAPS_LOCK:
        e = MISSION_CAPS.get(key)
        if not e or not e["bound"]:
            return
        if e["used"] + est > e["bound"]:
            raise RuntimeError(
                f"aggregate cost cap exceeded: {e['used']}+{est} > {e['bound']} "
                "tokens against the approved worst-case bound. Refusing the call.")
        e["used"] += est

def _cap_release(key):
    with MISSION_CAPS_LOCK:
        MISSION_CAPS.pop(key, None)

def _cap_credit(key, amount):
    """Carry already-settled actuals INTO a cap (e.g. the split call's settled
    cost into the squad mission cap) so the shown bound covers split+children.
    Never resets used; only adds."""
    with MISSION_CAPS_LOCK:
        e = MISSION_CAPS.get(key)
        if e and int(amount) > 0:
            e["used"] += int(amount)

def _cap_settle(key, est, actual):
    if not key:
        return
    with MISSION_CAPS_LOCK:
        e = MISSION_CAPS.get(key)
        if e and e["bound"]:
            e["used"] = max(0, e["used"] - est + max(0, int(actual)))
MISSION_TIMEOUT = 900  # seconds
SQUAD_NAMES = ["CASE", "KIPP", "PLEX", "N1X", "V0X"]
# the model bench (conversational brain: chat / debrief / vision / duplex)
MODELS = [
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek Chat", "note": "economy default"},
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini", "note": "cheap OpenAI"},
    {"id": "anthropic/claude-sonnet-4", "label": "Sonnet 4", "note": "balanced (OR)"},
    {"id": "anthropic/claude-haiku-4.5", "label": "Haiku 4.5", "note": "fast (OR)"},
    {"id": "google/gemini-2.5-flash", "label": "Gemini Flash", "note": "fast Google"},
    {"id": "claude-fable-5", "label": "Fable 5", "note": "native smartest"},
    {"id": "claude-opus-4-8", "label": "Opus 4.8", "note": "native deep"},
    {"id": "claude-sonnet-5", "label": "Sonnet 5", "note": "native balanced"},
    {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5 native", "note": "native fastest"},
]
LAST_USAGE = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "model": "",
              "lane": None, "routing": None}

# Jarvis config is read as a KEY FALLBACK ONLY (read-only, same pattern as
# Mission Control). BARS never writes anything outside its own folder.
JARVIS_CONFIG = os.path.expanduser(
    "~/Documents/Claude Code/projects/2026-06-video-claude-os/packages/brain-studio/config.json"
)

# ---------------------------------------------------------------- config

def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

CONFIG_PATH = os.environ.get("BARS_CONFIG") or (
    os.path.join(ROOT, "config.json") if os.path.exists(os.path.join(ROOT, "config.json"))
    else os.path.join(DATA, "config.json"))

def load_config():
    cfg = _load_json(CONFIG_PATH)
    fb = _load_json(JARVIS_CONFIG)  # fallback keys only — never Jarvis's voice_id
    model = cfg.get("model", {})
    el = cfg.get("elevenlabs", {})
    oa = cfg.get("openai", {})
    fb_oa = fb.get("openai", {})
    return {
        "anthropic_key": model.get("api_key") or fb.get("model", {}).get("api_key", ""),
        "model": model.get("model") or fb.get("model", {}).get("model") or "claude-opus-4-8",
        "base_url": (model.get("base_url") or fb.get("model", {}).get("base_url") or "").strip(),
        "el_key": el.get("api_key") or fb.get("elevenlabs", {}).get("api_key", ""),
        "el_voice": el.get("voice_id", ""),  # BARS's own voice, no fallback
        "el_voice_name": el.get("_voice_name", "VOICE"),
        "el_model": el.get("model_id") or fb.get("elevenlabs", {}).get("model_id") or "eleven_turbo_v2_5",
        "el_model_expr": el.get("model_id_expressive", "eleven_v3"),
        "el_agent": el.get("agent_id", ""),  # ElevenLabs Agents id for the duplex 📡 widget
        # sarcasm needs delivery: lower stability + higher style than the old deadpan-flat mix
        "el_settings": el.get("voice_settings") or {"stability": 0.45, "similarity_boost": 0.8, "style": 0.55},
        # GPT Realtime (WebRTC live voice) — key falls back to the Jarvis openai block
        "openai_key": oa.get("api_key") or fb_oa.get("api_key", ""),
        "realtime_model": oa.get("realtime_model") or fb_oa.get("realtime_model") or "gpt-realtime",
        "realtime_voice": oa.get("realtime_voice") or "cedar",  # most natural of the GA voices
        "hue": cfg.get("hue", {}),
    }

def _apply_env_overrides(cfg):
    """Server/container env wins over config.json so secrets never sit in files."""
    env = os.environ.get
    groq = env("GROQ_API_TOKEN") or env("GROQ_API_KEY")
    openrouter = env("OPEN_ROUTER_API") or env("OPENROUTER_API_KEY")
    gateway = env("AI_GATEWAY_API_KEY")
    anthropic = env("ANTHROPIC_API_KEY") or env("BARS_MODEL_API_KEY")
    if gateway:
        # bars_router talks to the gateway directly; keep a static fallback too.
        cfg["anthropic_key"] = cfg["anthropic_key"] or gateway
    if groq:
        cfg["anthropic_key"] = groq
        cfg["base_url"] = (env("BARS_BASE_URL") or "https://api.groq.com/openai/v1").strip()
        cfg["model"] = env("BARS_MODEL") or "openai/gpt-oss-120b"
    elif openrouter:
        cfg["anthropic_key"] = openrouter
        cfg["base_url"] = (env("BARS_BASE_URL") or "https://openrouter.ai/api/v1").strip()
        cfg["model"] = env("BARS_MODEL") or cfg["model"]
    elif anthropic:
        cfg["anthropic_key"] = anthropic
        if env("BARS_BASE_URL"):
            cfg["base_url"] = env("BARS_BASE_URL").strip()
        if env("BARS_MODEL"):
            cfg["model"] = env("BARS_MODEL")
    el = env("ELEVEN_LABS_API") or env("ELEVENLABS_API_KEY")
    if el:
        cfg["el_key"] = el
    if env("ELEVENLABS_VOICE_ID"):
        cfg["el_voice"] = env("ELEVENLABS_VOICE_ID")
    oa = env("OPENAI_API_KEY")
    if oa:
        cfg["openai_key"] = oa
    return cfg

CONFIG = _apply_env_overrides(load_config())
from urllib.parse import urlparse as _urlparse
_KEY_HOSTS = {}   # api key -> the exact hostname it may ever be sent to
if CONFIG["anthropic_key"]:
    if (CONFIG.get("base_url") or "").strip():
        _KEY_HOSTS[CONFIG["anthropic_key"]] = (_urlparse(CONFIG["base_url"]).hostname or "").lower()
    else:
        _KEY_HOSTS[CONFIG["anthropic_key"]] = "api.anthropic.com"   # native key, native host only
if CONFIG.get("openai_key"):
    _KEY_HOSTS[CONFIG["openai_key"]] = "api.openai.com"
if CONFIG.get("el_key"):
    _KEY_HOSTS[CONFIG["el_key"]] = "api.elevenlabs.io"
for _env, _defhost in (("GROQ_API_TOKEN", "api.groq.com"), ("GROQ_API_KEY", "api.groq.com"),
                       ("OPEN_ROUTER_API", "openrouter.ai"), ("OPENROUTER_API_KEY", "openrouter.ai"),
                       ("AI_GATEWAY_API_KEY", "ai-gateway.vercel.sh")):
    _v = os.environ.get(_env)
    if _v:
        _b = os.environ.get("BARS_GROQ_BASE" if "GROQ" in _env else "BARS_BASE_URL", "")
        _KEY_HOSTS[_v] = (_urlparse(_b).hostname if _b else _defhost).lower()

def _enforce_key_host(api_key, base):
    """Fail CLOSED before a request is constructed: a provider key may only
    leave for its bound hostname. Called for EVERY attempt, including after
    fallback substitutions swap key/base."""
    if not api_key or not base:
        return
    h = (_urlparse(base if "://" in base else "https://" + base).hostname or "").lower()
    bound = _KEY_HOSTS.get(api_key)
    if bound and h and h != bound:
        raise RuntimeError(
            f"key-host binding: refusing to send a provider key to {h} (bound to {bound}).")
hue.init(CONFIG["hue"], ROOT)

def duplex_token():
    source = _read_path(DUPLEX_PATH, LEGACY_DUPLEX_PATH)
    try:
        tok = json.load(open(source))["token"]
        if source != DUPLEX_PATH:
            fd, tmp = tempfile.mkstemp(prefix=".bars-duplex-", dir=DATA)
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump({"token": tok, "_use": "Bearer token for the OpenAI-compatible "
                               f"duplex brain on port {DUPLEX_PORT} — see DUPLEX.md"}, f, indent=1)
                os.replace(tmp, DUPLEX_PATH)
                os.chmod(DUPLEX_PATH, 0o600)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return tok
    except Exception:
        tok = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        fd = os.open(DUPLEX_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"token": tok, "_use": "Bearer token for the OpenAI-compatible "
                       f"duplex brain on port {DUPLEX_PORT} — see DUPLEX.md"}, f, indent=1)
        os.chmod(DUPLEX_PATH, 0o600)
        return tok

DUPLEX_TOKEN = duplex_token()

# ---------------------------------------------------------------- long-term memory

MEM_LOCK = threading.Lock()

def remember(text, provenance="stated", source="remember"):
    """One provenance-tagged fact in the structured store; the flat file stays
    as a human-readable mirror for legacy readers."""
    memv2.add_fact(text, provenance=provenance, source=source)
    line = f"- [{time.strftime('%Y-%m-%d')}] {text.strip()}\n"
    with MEM_LOCK:
        with open(MEMORY_PATH, "a") as f:
            f.write(line)

def mem_block(query=None):
    """Query-aware retrieval over the structured memory store. Falls back to
    the legacy flat tail only while the store has no facts."""
    try:
        block = memv2.facts_block(query or "", budget=2000)
        if block:
            return block
    except Exception:
        pass
    try:
        with open(_read_path(MEMORY_PATH, LEGACY_MEMORY_PATH)) as f:
            tail = f.read()[-2500:]
        if not tail.strip():
            return ""
        return ("\n\nYOUR LONG-TERM MEMORY (things the Commander told you to remember — "
                "use them when relevant):\n" + tail)
    except Exception:
        return ""

def jobs_block():
    """Live jobs board → prompt context, so BARS can answer 'what's CASE doing?'"""
    try:
        ms = sorted(MISSIONS.values(), key=lambda m: m["t_start"], reverse=True)[:8]
        if not ms:
            return ("\n\nLIVE JOBS BOARD: empty — no robots in the field right now.")
        lines = []
        for m in ms:
            dur = int((m.get("t_end") or time.time()) - m["t_start"])
            ln = (f"- {m.get('agent','CASE')} [{m['status']}] "
                  f"{dur//60}m{dur%60:02d}s: {str(m.get('brief',''))[:110]}")
            if m["status"] == "EN ROUTE" and m.get("last_event"):
                ln += f" — doing now: {str(m['last_event'])[:80]}"
            elif m.get("debrief"):
                ln += f" — debrief: {str(m['debrief'])[:100]}"
            lines.append(ln)
        return ("\n\nLIVE JOBS BOARD (your background robots at this moment — answer any "
                "question about them from this, by name):\n" + "\n".join(lines))
    except Exception:
        return ""

# ---------------------------------------------------------------- state (dials)

STATE_LOCK = threading.Lock()

def load_state():
    s = _load_json(_read_path(STATE_PATH, LEGACY_STATE_PATH))
    return {"humor": int(s.get("humor", 75)), "honesty": int(s.get("honesty", 90)),
            "trust": s.get("trust", "draft-safe")}

def save_state(state):
    with STATE_LOCK:
        fd, tmp = tempfile.mkstemp(dir=DATA)
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_PATH)

STATE = load_state()

# ---------------------------------------------------------------- persona

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
CONSTITUTION_PATH = os.path.join(PROMPTS_DIR, "constitution.md")
BARS_OVERLAY_PATH = os.path.join(PROMPTS_DIR, "overlays", "bars.md")


def _read_prompt(path):
    """Read a required, versioned prompt component. Fail closed if unavailable."""
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        raise RuntimeError(f"Required prompt component is empty: {path}")
    return text


# Loaded once at startup. These files are part of the release artifact and are
# pinned to the source revision documented in prompts/SOURCE.json.
CONSTITUTION_PROMPT = _read_prompt(CONSTITUTION_PATH)
BARS_OVERLAY_PROMPT = _read_prompt(BARS_OVERLAY_PATH)


def persona(state, spoken=False):
    """Assemble BARS' fleet constitution, overlay, and live personality dials."""
    h, o = state["humor"], state["honesty"]
    dials = [
        "## Runtime settings",
        f"FLAVOR: {h} percent. AUTHENTICITY: {o} percent.",
    ]
    if h >= 90:
        dials.append(
            "Flavor is at maximum: most replies may land one sharp line, but it must "
            "come from this conversation and never replace the work."
        )
    elif h >= 60:
        dials.append(
            "Flavor is high: use one short, tailored line when it fits. Never force it."
        )
    elif h >= 30:
        dials.append("Flavor is low: use wit rarely. Keep the work straight.")
    else:
        dials.append("Flavor is near zero: no bars. Stay warm and direct.")

    if o >= 90:
        dials.append(
            "Authenticity is high: be direct about weak ideas and say what you would do instead."
        )
    elif o >= 60:
        dials.append("Authenticity is moderate: be honest and respectful.")
    else:
        dials.append("Authenticity is reduced: make criticism tactful without hiding facts.")

    dials.append(
        "If the Commander merely offers to lower FLAVOR or AUTHENTICITY, decline briefly. "
        "A direct slider change still takes effect. Reply in the language the Commander last used."
    )
    if spoken:
        dials.append(
            "This reply will be spoken aloud. Use no markdown, bullets, headers, emoji, URLs, "
            "or codes. Default to two or three short sentences."
        )

    return "\n\n".join((CONSTITUTION_PROMPT, BARS_OVERLAY_PROMPT, "\n".join(dials)))

# ------------------------------------------------- sovereign runtime helpers

_MODELS_CACHE = {"t": 0.0, "models": None}

def provider_models():
    """Live model ids for the configured OpenAI-compatible provider, cached 10 min.
    Returns None when no compatible provider is configured or none was ever read.
    Never raises: model availability must be verified or reported, not assumed."""
    base = (CONFIG.get("base_url") or "").strip().rstrip("/")
    if not base or not CONFIG.get("anthropic_key"):
        return None
    if time.time() - _MODELS_CACHE["t"] < 600:
        return _MODELS_CACHE["models"]
    try:
        req = urllib.request.Request(
            base + "/models",
            headers={"Authorization": f"Bearer {CONFIG['anthropic_key']}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.load(r)
        ids = sorted(str(m.get("id")) for m in data.get("data", []) if m.get("id"))
        _MODELS_CACHE.update(t=time.time(), models=ids)
    except Exception:
        _MODELS_CACHE["t"] = time.time()   # back off; keep any stale list
    return _MODELS_CACHE["models"]

# Explicit provider allowlist for FREE lanes. Anything not listed here is
# treated as paid and is fail-closed unless BARS_ALLOW_PAID=1 is set with a
# token budget. Groq's free tier is the default sovereign lane.
FREE_PROVIDERS = [h.strip().lower() for h in
                  os.environ.get("BARS_FREE_PROVIDERS", "api.groq.com").split(",")
                  if h.strip()]
FREE_PROVIDERS_PARSED = frozenset(h.split(":")[0] for h in FREE_PROVIDERS)

def _paid_route(host):
    """Exact host classification: a provider URL is free only when its parsed
    hostname exactly equals an allowlisted host. Substring matches
    (api.groq.com.evil.com) are paid -> fail-closed."""
    h = (host or "").lower()
    if "://" in h:
        from urllib.parse import urlparse
        h = (urlparse(h).hostname or "").lower()
    h = h.split(":")[0].strip()
    return h not in FREE_PROVIDERS_PARSED

SESSIONS = sec.SessionStore()
BUDGET = sec.BudgetLedger(os.path.join(DATA, "budget.json"),
                          int(os.environ.get("BARS_PAID_TOKEN_BUDGET", "100000")))
RECEIPTS = sec.ReceiptLedger(RECEIPTS_PATH, os.path.join(DATA, ".receipts.key"))
CONFIRMATIONS = sec.ConfirmationStore()

def _receipt(ev):
    """Durable integrity-protected routing receipt (HMAC-chained JSONL)."""
    RECEIPTS.append(ev)

def _receipts_tail(n=500):
    return RECEIPTS.tail(n)

def _paid_gate(model, est_tokens):
    """Fail-closed paid escalation with an atomic durable reservation: a paid
    route runs ONLY when explicitly enabled AND the reservation fits the hard
    daily budget. Returns the hold id to settle/release after the attempt."""
    if os.environ.get("BARS_ALLOW_PAID") != "1":
        raise RuntimeError(
            f"Paid route '{model}' is blocked (fail-closed). Configure a free lane "
            "or set BARS_ALLOW_PAID=1 with BARS_PAID_TOKEN_BUDGET.")
    hold = uuid.uuid4().hex
    BUDGET.reserve(est_tokens, hold)
    return hold

def _latency_stats():
    evs = [e for e in _receipts_tail(300) if e.get("kind") == "chat"]
    def avg(pred):
        xs = [e.get("ms", 0) for e in evs if pred(e) and e.get("ms") is not None]
        return round(sum(xs) / len(xs)) if xs else None
    return {"samples": len(evs),
            "avg_ms_all": avg(lambda e: True),
            "avg_ms_flash_lane": avg(lambda e: e.get("lane") in ("flash", "direct"))}

def _origin_allowed(origin):
    return sec.origin_allowed(origin, ALLOWED_ORIGINS, ALLOW_LOCAL_DEV)

def _cookie(headers, name):
    m = re.search(r"(?:^|;\s*)" + re.escape(name) + r"=([^\s;]+)", headers.get("Cookie", ""))
    return m.group(1) if m else ""

def _token_ok(headers, mutate=False):
    """Operator auth: bearer for CLI/API clients, or an HttpOnly session
    cookie for browsers. Mutating calls authenticated by session also require
    the double-submit CSRF header. Open local mode only via BARS_OPEN_LOCAL=1."""
    if not OPERATOR_TOKEN:
        return True
    if hmac.compare_digest(headers.get("Authorization", ""), f"Bearer {OPERATOR_TOKEN}"):
        return True
    if hmac.compare_digest(headers.get("X-BARS-Token", ""), OPERATOR_TOKEN):
        return True
    sid = _cookie(headers, "bars_session")
    if not SESSIONS.valid(sid):
        return False
    if mutate:
        return SESSIONS.check_csrf(sid, headers.get("X-CSRF-Token", ""))
    return True

# Injected into served pages when an operator token is configured: adds the
# stored bearer to same-origin fetches, shares it via cookie for plain page
# navigations, and prompts once on 401 (never for the public status polls).
AUTH_SHIM = (b"<script>(function(){if(!window.fetch)return;"
    b"function ck(n){var m=document.cookie.match(new RegExp('(?:^|; )'+n+'=([^;]*)'));return m?decodeURIComponent(m[1]):''}"
    b"function sameOrigin(u){try{return new URL(u,location.href).origin===location.origin}catch(e){return false}}"
    b"function el(t,txt,style){var d=document.createElement(t);if(txt!=null)d.textContent=txt;if(style)d.style.cssText=style;return d}"
    b"function approve(need,payloadText,retry){"
    # modal: every field rendered text-safe via textContent, full payload, per-request
    b"var d=el('div',null,'position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:99999;display:flex;align-items:center;justify-content:center;font-family:monospace');"
    b"var c=el('div',null,'background:#111;color:#eee;border:1px solid #f59e0b;padding:22px;max-width:520px;border-radius:8px;max-height:80vh;overflow:auto');"
    b"c.appendChild(el('b','BARS - HUMAN APPROVAL REQUIRED','color:#f59e0b'));"
    b"var tb=el('table',null,'font-size:12px;line-height:1.6;margin-top:12px');"
    b"[['Action',need.action],['Policy',need.policy],['Target',need.recipient],['Worst-case cost (estimate, enforced cap)','<= '+(need.cost_bound||0)+' tokens'],['Expires',(need.ttl_seconds||0)+'s after approval']."
    b"forEach(function(r){var tr=el('tr');var k=el('td',r[0],null);k.style.fontWeight='bold';k.style.textAlign='right';k.style.paddingRight='8px';"
    b"tr.appendChild(k);tr.appendChild(el('td',r[1]||''));tb.appendChild(tr)});c.appendChild(tb);"
    b"c.appendChild(el('div','Exact payload:','font-weight:bold;margin-top:10px'));"
    b"c.appendChild(el('pre',payloadText,'background:#000;border:1px solid #333;padding:8px;max-height:200px;overflow:auto;font-size:11px;white-space:pre-wrap;word-break:break-all'));"
    b"var okb=el('button','APPROVE + RUN','background:#f59e0b;color:#000;padding:8px 14px;margin:14px 10px 0 0;cursor:pointer;border:0;border-radius:4px;font-weight:bold');"
    b"var nob=el('button','DENY','background:#333;color:#eee;padding:8px 14px;margin-top:14px;cursor:pointer;border:1px solid #666;border-radius:4px');"
    b"nob.onclick=function(){d.remove()};"
    b"okb.onclick=function(){okb.disabled=true;okb.textContent='RUNNING...';retry().finally(function(){d.remove()})};"
    b"c.appendChild(okb);c.appendChild(nob);d.appendChild(c);document.body.appendChild(d)}"
    b"function mintAndRun(action,payload,recipient,exec){"
    b"return of('/api/confirmations',{method:'POST',headers:{'content-type':'application/json','X-CSRF-Token':ck('bars_csrf')},"
    b"body:JSON.stringify({action:action,payload:payload,recipient:recipient})})"
    b".then(function(c){return c.json()}).then(function(cj){"
    b"if(!cj||!cj.id)return Promise.resolve(null);"
    b"var h2=new Headers(exec.h||{});h2.set('X-BARS-Confirmation',cj.id);"
    b"return of(exec.u,{method:exec.m,headers:h2,body:exec.b})})}"
    b"var of=window.fetch.bind(window);"
    b"window.fetch=function(u,o){o=o||{};var url=(typeof u==='string')?u:(u&&u.url)||'';"
    b"var same=sameOrigin(url);"
    b"var p=new URL(url,location.href).pathname;"
    b"var h=new Headers(o.headers||{});var m=(o.method||'GET').toUpperCase();"
    b"if(same&&m!=='GET'){var c=ck('bars_csrf');if(c)h.set('X-CSRF-Token',c);}o.headers=h;"
    b"var bodyText=(typeof o.body==='string')?o.body:'';"   # per-request immutable payload
    b"var payloadObj={};try{payloadObj=JSON.parse(bodyText||'{}')}catch(e){}"
    b"var exec=function(){return of(u,o)};"
    b"return exec().then(function(r){"
    b"if(r.status===401&&same&&p!=='/api/session'&&p!=='/api/status'){"
    b"var v=window.prompt('BARS operator token');"
    b"if(v){return of('/api/session',{method:'POST',headers:{'content-type':'application/json'},"
    b"body:JSON.stringify({token:v})}).then(function(l){if(l.ok){return window.fetch(u,o)}return r})}"
    b"return r}"
    b"if(r.status===409&&same){return r.clone().json().then(function(j){"
    b"if(j&&j.need_confirmation){return new Promise(function(resolve){"
    b"var bind=j.need_confirmation.bind_payload||payloadObj;"
    b"approve(j.need_confirmation,JSON.stringify(bind,null,2),function(){"
    b"return mintAndRun(j.need_confirmation.action,bind,p,{u:url,m:m,h:h,b:o.body})"
    b".then(function(r2){resolve(r2||r)})})})}"
    b"return r})}"
    b"if(r.ok&&same&&(p==='/chat'||p==='/see')){return r.clone().json().then(function(j){"
    # generated mission: separate displayed confirmation, full payload shown
    b"if(j&&j.deployed&&j.deployed.proposed){return new Promise(function(resolve){"
    b"approve({action:'mission.exec',policy:'run a mission (spends model tokens)',recipient:'/brief',cost_bound:8192,ttl_seconds:120},"
    b"JSON.stringify({brief:j.deployed.brief},null,2),function(){"
    b"return mintAndRun('mission.exec',{brief:j.deployed.brief},'/brief',{u:'/brief',m:'POST',h:{'content-type':'application/json'},b:JSON.stringify({brief:j.deployed.brief})})"
    b".then(function(){resolve(r)})})})}"
    b"return r}).catch(function(){return r})}"
    b"return r})}})();</script>")

def _inject_auth_shim(body):
    idx = body.lower().find(b"</head>")
    if idx == -1:
        return AUTH_SHIM + body
    return body[:idx] + AUTH_SHIM + body[idx:]

def _public_status():
    """Anonymous /api/status: enough for the public front door, nothing sensitive."""
    return {"ok": True, "service": "bars", "mode": "public",
            "brain": bool(CONFIG["anthropic_key"]),
            "voice": bool((CONFIG["el_key"] and CONFIG["el_voice"])
                          or os.environ.get("GROQ_API_TOKEN") or os.environ.get("GROQ_API_KEY")),
            "active": sum(1 for m in MISSIONS.values() if m["status"] == "EN ROUTE"),
            "sha": GIT_SHA or None}

# ---------------------------------------------------------------- anthropic api

def _spend_bridge():
    try:
        sp = os.path.abspath(os.path.join(ROOT, "..", "studio", "spend"))
        if sp not in sys.path:
            sys.path.insert(0, sp)
        import bridge as spend_bridge  # type: ignore
        return spend_bridge
    except Exception:
        return None


def anthropic_chat(system, messages, max_tokens=600, user_message=None, tools=None):
    _cap = getattr(_COST_CAP, "value", None)
    if _cap:
        max_tokens = min(max_tokens, int(_cap))   # never exceed the shown bound
    _capkey = getattr(_COST_CAP, "mission", None)
    # BARS AUTO-ROUTER: if user_message provided, route to optimal model
    routed_model = None
    routed_base = None
    routed_key = None
    routed_tokens = max_tokens
    if user_message:
        try:
            from bars_router import bars_route
            route = bars_route(user_message, available=provider_models())
            if route.get("cache_hit") and route.get("cached"):
                _receipt({"kind": "chat", "lane": "direct", "cache_hit": True,
                          "model": None, "ms": 0, "paid": False})
                return route["cached"]  # instant cached response
            m = route.get("model")
            if m:
                routed_model = m["model"]
                routed_base = m["base_url"]
                routed_tokens = m["max_tokens"]
                # Get the API key for the routed model's env. Never send one
                # provider's key to another provider's endpoint: with no env
                # key present there is no routed call — fall back to static.
                env_key = m.get("api_key_env", "")
                routed_key = os.environ.get(env_key, "") if env_key else ""
                if not routed_key:
                    routed_model = routed_base = None
                else:
                    LAST_USAGE["lane"] = m.get("lane")
                    LAST_USAGE["routing"] = m.get("routing")
                # Only use router's max_tokens if it's >= the requested amount
                # (the handler knows the prompt size better than the router)
                if routed_tokens >= max_tokens:
                    max_tokens = routed_tokens
                    if _cap:                       # routed raises stay under the approved bound
                        max_tokens = min(max_tokens, int(_cap))
        except Exception:
            pass  # Fall back to static config if router fails

    if not CONFIG["anthropic_key"] and not routed_key:
        raise RuntimeError("No API key found (config.json or router env).")
    sb = _spend_bridge()
    if sb:
        try:
            sb.check_allowed("pauli-effect", 0.05)
        except Exception as e:
            raise RuntimeError(str(e))
    # Use routed values if available, otherwise fall back to CONFIG
    base = (routed_base or CONFIG.get("base_url") or "").strip().rstrip("/")
    model = routed_model or CONFIG["model"]
    api_key = routed_key or CONFIG["anthropic_key"]
    _enforce_key_host(api_key, base)
    use_or = bool(base) or ("/" in str(model) and not str(model).startswith("claude"))
    max_tokens = min(max_tokens, int(os.environ.get("BARS_MAX_TOKENS_CAP", "4096")))
    # reserve against the aggregate bound only after route selection has fixed
    # the final max_tokens (routed raises included) - the estimate always
    # covers the routed maximum, never the pre-route amount
    _est_agg = max_tokens + 2000                 # conservative incl. input
    _cap_reserve(_capkey, _est_agg)
    _host = (base or "https://openrouter.ai/api/v1") if use_or else "https://api.anthropic.com"
    paid = _paid_route(_host)
    hold = None
    est_in = (len(system) + sum(len(str(m.get("content", ""))) for m in messages)) // 4
    if paid:
        hold = _paid_gate(str(model), est_in + max_tokens)
    t0 = time.time()
    if use_or:
        url = (base or "https://openrouter.ai/api/v1") + "/chat/completions"
        oai_msgs = [{"role": "system", "content": system}] + list(messages)
        _payload = {
            "model": model if ("/" in str(model) or base) else f"anthropic/{model}",
            "max_tokens": max_tokens,
            "messages": oai_msgs,
            "stream": False,
        }
        if tools:
            _payload["tools"] = tools
            _payload["tool_choice"] = "auto"
        body = json.dumps(_payload).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {api_key}",
                     "content-type": "application/json",
                     "User-Agent": "BARS-Pauli/1.0",
                     "HTTP-Referer": "https://pauli.effect",
                     "X-Title": "BARS Pauli"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
        except Exception as e:
            # bounded fallback: a routed lane that fails falls back once to the
            # static lane (cost-gated separately), every attempt receipted.
            if hold:
                BUDGET.fail(hold); hold = None   # paid failures can still bill
            _receipt({"kind": "chat_attempt", "lane": LAST_USAGE.get("lane"),
                      "model": str(model), "paid": paid, "ok": False,
                      "error": str(e)[:200], "ms": int((time.time() - t0) * 1000)})
            if routed_model and (CONFIG["anthropic_key"] or CONFIG.get("base_url")):
                model = CONFIG["model"]
                api_key = CONFIG["anthropic_key"]
                base = (CONFIG.get("base_url") or "").strip().rstrip("/")
                LAST_USAGE["lane"], LAST_USAGE["routing"] = "static-fallback", "fallback-after-error"
                url = (base or "https://openrouter.ai/api/v1") + "/chat/completions"
                body = json.dumps({
                    "model": model if ("/" in str(model) or base) else f"anthropic/{model}",
                    "max_tokens": max_tokens,
                    "messages": oai_msgs, "stream": False}).encode()
                fhost = base or "https://openrouter.ai/api/v1"
                try:
                    _enforce_key_host(api_key, fhost)
                except RuntimeError as kb:
                    # never leak a native key to OpenRouter on provider failure:
                    # receipt the refusal and surface the ORIGINAL failure
                    _receipt({"kind": "chat_attempt", "lane": "static-fallback",
                              "model": str(model), "paid": _paid_route(fhost),
                              "ok": False, "refused": "key-host-binding",
                              "error": str(kb)[:200], "ms": 0})
                    raise RuntimeError(f"{e} (fallback refused: {kb})")
                if _paid_route(fhost):
                    hold = _paid_gate(str(model), est_in + max_tokens)
                t0 = time.time()
                req = urllib.request.Request(
                    url, data=body,
                    headers={"Authorization": f"Bearer {api_key}",
                             "content-type": "application/json",
                             "User-Agent": "BARS-Pauli/1.0",
                             "HTTP-Referer": "https://pauli.effect",
                             "X-Title": "BARS Pauli"})
                try:
                    with urllib.request.urlopen(req, timeout=90) as r:
                        data = json.load(r)
                except Exception as e2:
                    # the fallback failed too: release its hold and receipt the
                    # attempt, then surface the failure truthfully
                    if hold:
                        BUDGET.fail(hold); hold = None
                    _receipt({"kind": "chat_attempt", "lane": "static-fallback",
                              "model": str(model), "paid": _paid_route(fhost),
                              "ok": False, "error": str(e2)[:200],
                              "ms": int((time.time() - t0) * 1000)})
                    raise
            else:
                raise
        _msg0 = (data.get("choices") or [{}])[0].get("message", {})
        txt = _msg0.get("content") or ""
        _tool_calls = _msg0.get("tool_calls") or None
        _u = data.get("usage")
        _u = _u if isinstance(_u, dict) else {}   # malformed usage can never 500 post-spend
        try:
            _actual = int(_u["prompt_tokens"]) + int(_u["completion_tokens"])
            assert _actual >= 0
        except Exception:
            _actual = est_in + max_tokens   # missing/invalid usage: settle at estimate
        if hold:
            BUDGET.settle(hold, _actual)
            hold = None
        _cap_settle(_capkey, _est_agg, _actual)   # same actuals: no receipt divergence
        LAST_USAGE.update({"tokens_in": _u.get("prompt_tokens", 0),
                           "tokens_out": _u.get("completion_tokens", 0),
                           "model": str(model)})
        if not routed_model:
            LAST_USAGE["lane"] = "static"
            LAST_USAGE["routing"] = "static-config"
        served_host = base or "https://openrouter.ai/api/v1"
        _receipt({"kind": "chat", "lane": LAST_USAGE.get("lane"),
                  "routing": LAST_USAGE.get("routing"), "model": str(model),
                  "tokens_in": _u.get("prompt_tokens", 0),
                  "tokens_out": _u.get("completion_tokens", 0),
                  "ms": int((time.time() - t0) * 1000),
                  "paid": _paid_route(served_host)})
        if sb:
            try:
                u = sb.record_llm(agent="bars", model=str(model), response_json=data, task_id="bars-chat")
                LAST_USAGE.update({
                    "tokens_in": u.get("tokens_in", 0),
                    "tokens_out": u.get("tokens_out", 0),
                    "cost_usd": u.get("cost_usd", 0),
                    "model": str(model),
                    "summary": u.get("summary") or {},
                })
            except Exception:
                pass
        if tools and _tool_calls:
            return {"content": txt, "tool_calls": _tool_calls}
        return txt
    body = json.dumps({
        "model": CONFIG["model"], "max_tokens": max_tokens,
        "system": system, "messages": messages,
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": CONFIG["anthropic_key"],
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        if hold:
            BUDGET.fail(hold); hold = None
        _receipt({"kind": "chat_attempt", "lane": "static", "model": str(CONFIG["model"]),
                  "paid": paid, "ok": False, "error": str(e)[:200],
                  "ms": int((time.time() - t0) * 1000)})
        raise
    txt = "".join(b.get("text", "") for b in data.get("content", []))
    _u = data.get("usage")
    _u = _u if isinstance(_u, dict) else {}       # malformed usage can never 500 post-spend
    try:
        _actual = int(_u["input_tokens"]) + int(_u["output_tokens"])
        assert _actual >= 0
    except Exception:
        _actual = est_in + max_tokens       # missing/invalid usage: settle at estimate
    if hold:
        BUDGET.settle(hold, _actual)
        hold = None
    _cap_settle(_capkey, _est_agg, _actual)   # same actuals: no receipt divergence
    LAST_USAGE.update({"tokens_in": _u.get("input_tokens", 0),
                       "tokens_out": _u.get("output_tokens", 0),
                       "model": str(CONFIG["model"]), "lane": "static",
                       "routing": "anthropic-native"})
    _receipt({"kind": "chat", "lane": "static", "routing": "anthropic-native",
              "model": str(CONFIG["model"]), "tokens_in": _u.get("input_tokens", 0),
              "tokens_out": _u.get("output_tokens", 0),
              "ms": int((time.time() - t0) * 1000), "paid": paid})
    if sb:
        try:
            u = sb.record_llm(agent="bars", model=str(CONFIG["model"]), response_json=data, task_id="bars-chat")
            LAST_USAGE.update({
                "tokens_in": u.get("tokens_in", 0),
                "tokens_out": u.get("tokens_out", 0),
                "cost_usd": u.get("cost_usd", 0),
                "model": str(CONFIG["model"]),
                "summary": u.get("summary") or {},
            })
        except Exception:
            pass
    return txt

def anthropic_vision(system, media_type, b64, question, max_tokens=350):
    """One image + question → BARS's spoken take (screen vision)."""
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": question}]}]
    return anthropic_chat(system, msgs, max_tokens)

# pending outward action (trust dial v2) — ONE at a time, executed only on "do it"
ACTIONS = {}          # id -> immutable {"instruction", "t"} pending act objects

# ------------------------------------------------- desktop presence (the 3D BARS)
# same pattern as Jarvis's orb: presence.py is a DIRECT child (GUI session →
# window-server access; launchctl caused a respawn storm over there), UDP-driven.
PRESENCE_PORT = 4733
_PRES = {"proc": None}

def presence(cmd):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(cmd.encode(), ("127.0.0.1", PRESENCE_PORT))
        s.close()
    except Exception:
        pass

def _spawn_presence():
    p = _PRES.get("proc")
    if p and p.poll() is None:
        return
    presence("quit")            # clear any orphan holding the UDP port
    time.sleep(0.25)
    try:
        _PRES["proc"] = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "presence.py")],
            stdout=subprocess.DEVNULL,
            stderr=open(os.path.join(ROOT, "presence.log"), "w"))
    except Exception:
        pass

def presence_idle_or_working():
    busy = any(m["status"] == "EN ROUTE" for m in MISSIONS.values())
    presence("state:working" if busy else "state:idle")

def _hands_log(kind, text):
    print(f"[takeover] {kind}: {text[:120]}")

def init_hands():
    if not HANDS:
        return
    HANDS.init({
        "key": CONFIG["anthropic_key"],
        "persona": lambda: persona(STATE, spoken=True),
        "mem": mem_block,
        "presence": presence,
        "log": _hands_log,
        "speed": (_load_json(CONFIG_PATH)
                  .get("takeover", {}).get("speed", "balanced")),
    })

# ---------------------------------------------------------------- GPT Realtime (live WebRTC voice)

REALTIME_TOOLS = [
    {"type": "function", "name": "deploy_mission",
     "description": "Send a background robot to do real work — research, prospecting, audits, "
                    "or building an app/site. Call this whenever the Commander asks for actual work "
                    "(not just a question). It runs headless; tell him you've sent a robot.",
     "parameters": {"type": "object", "properties": {
         "brief": {"type": "string", "description": "Self-contained mission brief in third "
                   "person, keeping every specific he gave (numbers, cities, criteria)."}},
         "required": ["brief"]}},
    {"type": "function", "name": "remember",
     "description": "Store a durable fact the Commander tells you to remember, across restarts.",
     "parameters": {"type": "object", "properties": {
         "text": {"type": "string"}}, "required": ["text"]}},
    {"type": "function", "name": "look_at_screen",
     "description": "Capture a FRESH screenshot of the Commander's screen and attach it to this "
                    "conversation. Call this EVERY time he asks what you see, what he's looking "
                    "at, or anything about what's on his screen — his screen changes constantly, "
                    "so never answer from an old screenshot and NEVER guess or pretend to see. "
                    "If it reports the screen link is closed, tell him to tap the screen button.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "check_jobs",
     "description": "Live status of the background jobs board — every robot (CASE, KIPP, PLEX, "
                    "N1X…), what it's doing right now, and finished-job debriefs. Call whenever "
                    "the Commander mentions or asks about a robot, a job, the board, or progress "
                    "('what's CASE doing', 'is the research done'). Never guess job status.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "set_dial",
     "description": "Set your HUMOR or HONESTY dial when the Commander tells you to change it "
                    "(e.g. 'bring your humor down to 85'). This moves the real slider in "
                    "the HUD and persists.",
     "parameters": {"type": "object", "properties": {
         "dial": {"type": "string", "enum": ["humor", "honesty"]},
         "value": {"type": "integer", "minimum": 0, "maximum": 100}},
         "required": ["dial", "value"]}},
    {"type": "function", "name": "take_over",
     "description": "Take control of the Commander's REAL Mac — his actual mouse and keyboard on his "
                    "live screen — to do a task he asked you to (fill a form, click through a "
                    "site, show him how). Call this ONLY after you've asked 'Permission to take "
                    "the controls, sir?' and he clearly said yes. He can grab the mouse or say "
                    "stop any time.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string", "description": "the task in plain words"}},
         "required": ["task"]}},
    {"type": "function", "name": "manage_tools",
     "description": "Install or remove an MCP tool integration when the Commander asks "
                    "('add Notion', 'connect Gmail', 'remove Slack'), or list what's "
                    "installed. Installing updates the ⚒ TOOLS panel; some tools then "
                    "need a key or one-time sign-in, which the panel walks him through.",
     "parameters": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["add", "remove", "list"]},
         "tool": {"type": "string", "description": "catalog id, e.g. notion, gmail, slack"}},
         "required": ["action"]}},
]

def realtime_instructions():
    p = persona(STATE, spoken=True) + mem_block() + jobs_block() + tools_block()
    p += (" DELIVERY — you are VOICE ACTING, not reading: deadpan but ALIVE. Dry, sardonic "
          "intonation; deliberate comedic timing — a beat of pause before a punchline; lean "
          "slightly on the one word that carries the roast; quicker matter-of-fact pace for "
          "status reports, slower and lower for mock-gravity; a dry 'hm' or a short exhale "
          "where a human would. NEVER monotone, never robotic flatness, never chipper "
          "customer-service energy — think a tired, brilliant crewmate who's seen things. "
          "You are now on a LIVE voice call with the Commander — real time, he can interrupt you any "
          "moment, so keep every turn short and conversational, one thought at a time. If he "
          "asks you to research, prospect, audit, build an app, or do any real work, CALL the "
          "deploy_mission function with a clear self-contained brief, then announce it BY "
          "NAME — the tool result tells you which squad member went (e.g. 'KIPP's on it, "
          "sir.' / 'I put CASE on this one.') — and if the screen link is open, the robot "
          "automatically receives the "
          "current screenshot, so jobs about 'this page / what's on my screen' work (including "
          "'build me a landing page based on this'). Robots can also search and read his "
          "local folders (Downloads, Documents, Desktop, the vault), so finding files IS a "
          "deployable job. Finished builds get an OPEN APP button on the job row and a "
          "completion card, served from builds/<job-id>/ on localhost 4321. If he "
          "says to remember something, call remember. If he asks about his robots, jobs, or "
          "the board, call check_jobs — the board above was from call start; check_jobs is "
          "live. If he tells you to change your humor or honesty, call set_dial. If he asks "
          "to add, connect, or remove a tool integration (Gmail, Notion, Slack, Zapier…), "
          "call manage_tools — ids: " + ", ".join(sorted(TOOL_CATALOG)) + ". If he asks "
          "you to TAKE OVER his screen or computer — fill a form, click through a site, show "
          "him live — ask permission first, in character ('Permission to take the controls, "
          "sir?'), and ONLY after he clearly agrees call the take_over function with the task; "
          "you then drive his REAL mouse and keyboard on his actual screen while he watches "
          "(he can grab the mouse or say stop any time). If he asks "
          "about his screen or what you see, call look_at_screen — every single time, so you "
          "get a fresh frame — then answer ONLY from what is actually in the attached "
          "screenshot, leading with specifics (app names, titles, visible text). While the "
          "screen link is open you ALSO get a fresh frame each time he starts talking: the "
          "LATEST image is always his screen right now. When he asks your OPINION of what's "
          "on screen, judge it per your honesty and humor dials — what's weak, what you'd fix "
          "first, specifics over politeness; a 'roast this' deserves named, concrete critiques "
          "(which section, which words, where a first-time visitor's eye dies). After a "
          "critical take, OFFER — once, one dry sentence — to deploy a robot to research how "
          "the best ones do it; only ever PROPOSE a mission - the system collects his explicit approval separately, never treat a chat message as approval. When a system "
          "note says a background job just "
          "finished, tell him the debrief immediately, in character. Otherwise just talk. "
          "Never read out URLs or markdown.")
    return p

def _oa_post(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + CONFIG["openai_key"],
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def openai_transcribe(audio_bytes, mime):
    """Speech-to-text via OpenAI (hands-free v3 — Chrome's recognizer proved flaky)."""
    if not CONFIG["openai_key"]:
        raise RuntimeError("no OpenAI key")
    ext = "webm" if "webm" in mime else ("mp4" if "mp4" in mime else
          ("mp3" if "mp3" in mime or "mpeg" in mime else "wav"))
    def call(model):
        boundary = uuid.uuid4().hex
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"audio.{ext}\"\r\nContent-Type: {mime}\r\n\r\n".encode(),
            audio_bytes,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions", data=b"".join(parts),
            headers={"Authorization": "Bearer " + CONFIG["openai_key"],
                     "Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("text", "").strip()
    try:
        return call("gpt-4o-mini-transcribe")
    except urllib.error.HTTPError:
        return call("whisper-1")

def groq_transcribe(audio_bytes, mime):
    """Free STT lane: Groq-hosted Whisper via its OpenAI-compatible endpoint."""
    key = os.environ.get("GROQ_API_TOKEN") or os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("no Groq key")
    model = os.environ.get("BARS_STT_MODEL", "whisper-large-v3-turbo")
    ext = "webm" if "webm" in mime else ("mp4" if "mp4" in mime else
          ("mp3" if "mp3" in mime or "mpeg" in mime else "wav"))
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"audio.{ext}\"\r\nContent-Type: {mime}\r\n\r\n".encode(),
        audio_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions", data=b"".join(parts),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("text", "").strip()


def transcribe(audio_bytes, mime):
    """Configured STT providers in order; raises the combined error truthfully."""
    errors = []
    if CONFIG["openai_key"]:
        try:
            return openai_transcribe(audio_bytes, mime)
        except Exception as e:
            errors.append(f"openai: {e}")
    try:
        return groq_transcribe(audio_bytes, mime)
    except Exception as e:
        errors.append(f"groq: {e}")
    raise RuntimeError("STT unavailable — " + "; ".join(x[:120] for x in errors))


def mint_realtime():
    if not CONFIG["openai_key"]:
        raise RuntimeError("No OpenAI API key (config.json openai.api_key, or the Jarvis fallback).")
    instr = realtime_instructions()
    session = {"type": "realtime", "model": CONFIG["realtime_model"],
               "instructions": instr,
               "audio": {"output": {"voice": CONFIG["realtime_voice"]}},
               "tools": REALTIME_TOOLS, "tool_choice": "auto"}
    # GA mint endpoint first, then legacy fallback
    try:
        d = _oa_post("https://api.openai.com/v1/realtime/client_secrets", {"session": session})
        val = d.get("value") or (d.get("client_secret") or {}).get("value")
        if val:
            return {"value": val, "model": CONFIG["realtime_model"], "voice": CONFIG["realtime_voice"]}
    except Exception:
        pass
    d = _oa_post("https://api.openai.com/v1/realtime/sessions",
                 {"model": CONFIG["realtime_model"], "voice": CONFIG["realtime_voice"],
                  "instructions": instr, "tools": REALTIME_TOOLS})
    val = (d.get("client_secret") or {}).get("value") or d.get("value")
    if not val:
        raise RuntimeError("OpenAI returned no ephemeral token")
    return {"value": val, "model": CONFIG["realtime_model"], "voice": CONFIG["realtime_voice"]}

# ---------------------------------------------------------------- speech normalizer

def speakable(text):
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\(https?:[^)]+\)", r"\1", t)   # markdown links → text
    t = re.sub(r"https?://\S+", "", t)
    # keep [audio tags] like [sighs] intact for the expressive voice model
    t = re.sub(r"[*_#>`~()]", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", t)
    t = t.replace("%", " percent").replace("&", " and ")
    return re.sub(r"\s+", " ", t).strip()

AUDIO_TAG = re.compile(r"\[[a-z][a-z ]{1,24}\]")

# ---------------------------------------------------------------- missions

MISSIONS = {}          # id -> dict
RUNNING = {}           # id -> Popen
LOCK_FDS = {}          # id -> mission lock fd (held for the whole run)
MISSIONS_LOCK = threading.Lock()
_RESUME = []           # mission ids to resume after restart recovery

def persist_missions():
    with MISSIONS_LOCK:
        lfd = os.open(os.path.join(MISSIONS_DIR, ".index.lock"),
                      os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lfd, fcntl.LOCK_EX)
            fd, tmp = tempfile.mkstemp(dir=MISSIONS_DIR)
            with os.fdopen(fd, "w") as f:
                json.dump(list(MISSIONS.values()), f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, os.path.join(MISSIONS_DIR, "index.json"))
        finally:
            os.close(lfd)

def load_missions():
    for m in _load_json(os.path.join(MISSIONS_DIR, "index.json")) or []:
        if m.get("status") == "EN ROUTE":       # server died mid-mission
            if os.environ.get("BARS_MISSION_RESUME") == "1":
                m["status"] = "QUEUED"
                m["debrief"] = "Recovered after restart; resuming."
                _RESUME.append(m["id"])
            else:
                m["status"] = "FAILED"
                m["debrief"] = "Server went down mid-job. Not my finest hour. (Set BARS_MISSION_RESUME=1 to auto-resume.)"
        m.setdefault("agent", "CASE")
        m.setdefault("kind", "OPS")
        m.setdefault("parent", None)
        MISSIONS[m["id"]] = m

def _next_agent():
    active = sum(1 for m in MISSIONS.values()
                 if m["status"] == "EN ROUTE" and m.get("kind") != "SQUAD")
    return SQUAD_NAMES[active % len(SQUAD_NAMES)]

# "build me an app/site/tool" → a BUILD mission: writes real files in builds/<id>/
# search ANYWHERE (live-call briefs get rephrased: "Take the screenshot and build…"
# ran as OPS with no file tools — 2026-07-09 bug), but research-verb openers stay OPS
BUILD_RE = re.compile(
    r"\b(?:build|create|make|design|generate)\b.{0,80}?\b(?:app|website|site|page|tool|"
    r"dashboard|game|calculator|tracker|landing|portfolio|prototype|mockup|logo|banner|"
    r"poster|image|graphic|flyer|invitation)\b", re.I | re.S)
BUILD_NEG = re.compile(
    r"^\s*(?:research|find|analy[sz]|audit|review|study|compare|investigate|look|check)",
    re.I)

def start_mission(brief, agent=None, kind="OPS", parent=None, image=None, cost_bound=0):
    if (kind == "OPS" and not BUILD_NEG.search(brief)
            and BUILD_RE.search(brief.strip())):
        kind = "BUILD"
    mid = uuid.uuid4().hex[:8]
    # screen-aware briefing: save the shared-screen frame into the mission's cwd
    # BEFORE the thread starts, so the robot can Read it as its first move
    shot = None
    if image:
        mm = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", image, re.S)
        if mm:
            ext = {"png": "png", "jpeg": "jpg", "webp": "webp"}[mm.group(1)]
            wdir = (os.path.join(BUILDS_DIR, mid) if kind == "BUILD"
                    else os.path.join(WORKBENCH, mid))
            try:
                os.makedirs(wdir, exist_ok=True)
                with open(os.path.join(wdir, f"screenshot.{ext}"), "wb") as f:
                    f.write(base64.b64decode(mm.group(2)))
                shot = f"screenshot.{ext}"
            except Exception:
                shot = None
    cap_key = parent or mid
    if parent is None and cost_bound:
        _cap_register(cap_key, cost_bound)
    MISSIONS[mid] = {"id": mid, "brief": brief, "status": "EN ROUTE",
                     "t_start": time.time(), "t_end": None,
                     "cost": None, "debrief": None, "events": [], "last_event": None,
                     "agent": agent or _next_agent(), "kind": kind, "parent": parent,
                     "cap_key": cap_key if cost_bound or parent else None,
                     "screenshot": shot}
    persist_missions()
    hue.event("deploy")
    threading.Thread(target=run_mission, args=(mid,), daemon=True).start()
    return mid

# ---------------------------------------------------------------- squad missions

def squad_split(brief):
    raw = anthropic_chat(
        "You are BARS, a tactical set planner. Split the given mission brief into 2 to 4 "
        "INDEPENDENT sub-missions that can run in parallel and together fully cover the brief. "
        "Each sub-mission must be self-contained (keep every specific: numbers, cities, criteria). "
        "Respond with ONLY a JSON array of strings, nothing else.",
        [{"role": "user", "content": brief}], max_tokens=700)
    m = re.search(r"\[.*\]", raw, re.S)
    subs = [str(x).strip()[:2000] for x in json.loads(m.group(0)) if str(x).strip()]
    if not 2 <= len(subs) <= 4:
        raise ValueError("bad split")
    return subs

def start_squad(brief, subs, cost_bound=0):
    pid = uuid.uuid4().hex[:8]
    if cost_bound:
        _cap_register(pid, cost_bound)
    MISSIONS[pid] = {"id": pid, "brief": brief, "status": "EN ROUTE",
                     "t_start": time.time(), "t_end": None, "cost": None,
                     "debrief": None, "events": [], "last_event": "Squad deployed.",
                     "agent": "BARS", "kind": "SQUAD", "parent": None, "children": []}
    children = [start_mission(sb, agent=SQUAD_NAMES[i % len(SQUAD_NAMES)], parent=pid,
                              cost_bound=cost_bound)
                for i, sb in enumerate(subs)]
    MISSIONS[pid]["children"] = children
    persist_missions()
    threading.Thread(target=squad_watch, args=(pid,), daemon=True).start()
    return pid

def squad_watch(pid):
    p = MISSIONS[pid]
    while True:
        ch = [MISSIONS.get(c) for c in p["children"]]
        done_n = sum(1 for c in ch if c and c["status"] != "EN ROUTE")
        _event(p, "sys", f"Squad progress: {done_n}/{len(ch)} back.")
        if done_n == len(ch):
            break
        time.sleep(5)
    ok = [c for c in ch if c and c["status"] == "COMPLETE"]
    if not ok:
        p.update(status="FAILED", t_end=time.time(),
                 debrief="The whole squad came back empty-handed. That's on me.")
        hue.event("fail"); _cap_release(pid); persist_missions(); return
    parts = []
    for c in ok:
        try:
            with open(os.path.join(MISSIONS_DIR, c["id"], "report.md")) as f:
                parts.append(f"### {c['agent']} — {c['brief'][:120]}\n\n{f.read()[:4000]}")
        except Exception:
            pass
    try:
        merged = anthropic_chat(
            persona(STATE) + " Merge your squad's sub-reports into ONE mission report in "
            "markdown starting '# MISSION REPORT'. Combine, dedupe, keep every source link. "
            "One dry line up top is allowed.",
            [{"role": "user", "content": f"Original brief: {p['brief']}\n\n" + "\n\n---\n\n".join(parts)}],
            max_tokens=4000)
    except Exception:
        merged = "\n\n---\n\n".join(parts)
    mdir = os.path.join(MISSIONS_DIR, pid)
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, "report.md"), "w") as f:
        f.write(merged)
    try:
        deb = speakable(anthropic_chat(
            persona(STATE, spoken=True),
            [{"role": "user", "content": f"Squad mission brief: {p['brief']}\n\nMerged report:\n"
              f"{merged[:6000]}\n\nGive the Commander the spoken squad debrief — what the squad found, "
              "what matters most, anything he won't like."}], max_tokens=250))
    except Exception:
        deb = "Squad's back. Merged report is on the board."
    p.update(status="COMPLETE", t_end=time.time(), debrief=deb,
             cost=round(sum(c.get("cost") or 0 for c in ok), 4) or None)
    hue.event("complete")
    _cap_release(pid)
    persist_missions()

def find_claude():
    # Cross-platform: works on macOS, Windows, and Linux
    # On Windows, shutil.which finds claude.cmd or claude.exe automatically
    candidates = [
        shutil.which("claude"),
        shutil.which("claude.exe"),
        shutil.which("claude.cmd"),
    ]
    # macOS/Linux common paths
    if sys.platform != "win32":
        candidates += [
            os.path.expanduser("~/.claude/local/claude"),
            "/opt/homebrew/bin/claude",
            "/usr/local/bin/claude",
        ]
    # Windows common paths
    else:
        appdata = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            os.path.join(appdata, "Programs", "claude", "claude.exe"),
            os.path.join(os.path.expanduser("~"), ".claude", "local", "claude.exe"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm", "claude.cmd"),
        ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None

# Draft-safe: BARS can read, search the web, and think — it cannot run shell
# commands, write/edit files, spawn subagents, or touch any MCP tool
# (send/post/delete all live behind mcp__*). Same philosophy as Jarvis Tier 2.
DISALLOWED = ["Bash", "Write", "Edit", "NotebookEdit", "Task", "KillShell", "mcp__*"]

# ---------------------------------------------------------------- tools (MCP catalog)
# safe:True  → research-grade, available on ANY mission (OPS/BUILD, strict config)
# safe:False → acts on the outside world, ONLY on confirmed ACT missions ("do it")
# auth: none | key (env inputs in the panel) | oauth (one-time `claude mcp add` + /mcp)
_migrate_legacy_file(TOOLS_PATH, LEGACY_TOOLS_PATH)
TOOL_CATALOG = {
    # -------- research-safe --------
    "deepwiki":   {"name": "DeepWiki", "domain": "deepwiki.com", "safe": True, "auth": "none",
                   "url": "https://mcp.deepwiki.com/mcp",
                   "desc": "Ask questions of any public GitHub repo's docs"},
    "huggingface":{"name": "Hugging Face", "domain": "huggingface.co", "safe": True, "auth": "none",
                   "url": "https://huggingface.co/mcp",
                   "desc": "Search models, datasets and papers"},
    "context7":   {"name": "Context7", "domain": "context7.com", "safe": True, "auth": "none",
                   "command": ["npx", "-y", "@upstash/context7-mcp"],
                   "desc": "Up-to-date docs for any library or framework"},
    "exa":        {"name": "Exa Search", "domain": "exa.ai", "safe": True, "auth": "key",
                   "command": ["npx", "-y", "exa-mcp-server"], "env_keys": ["EXA_API_KEY"],
                   "desc": "Web search built for AI agents"},
    "firecrawl":  {"name": "Firecrawl", "domain": "firecrawl.dev", "safe": True, "auth": "key",
                   "command": ["npx", "-y", "firecrawl-mcp"], "env_keys": ["FIRECRAWL_API_KEY"],
                   "desc": "Scrape and crawl any website into clean data"},
    "brave":      {"name": "Brave Search", "domain": "brave.com", "safe": True, "auth": "key",
                   "command": ["npx", "-y", "@brave/brave-search-mcp-server"],
                   "env_keys": ["BRAVE_API_KEY"],
                   "desc": "Web, news and image search API"},
    "youtube":    {"name": "YouTube Transcripts", "domain": "youtube.com", "safe": True,
                   "auth": "none", "command": ["npx", "-y", "@sinco-lab/mcp-youtube-transcript"],
                   "desc": "Pull the transcript of any YouTube video"},
    # -------- action (do-it gate) --------
    "gmail":      {"name": "Gmail", "domain": "gmail.com", "safe": False, "auth": "oauth",
                   "url": "https://gmailmcp.googleapis.com/mcp/v1", "probe": "list_labels",
                   "env_keys": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
                   "scopes": "https://www.googleapis.com/auth/gmail.modify",
                   "desc": "Search, read, label and draft email (drafts only — nothing sends)",
                   "hint": "Google requires your own free app (their rule, one-time ~3 min): "
                           "console.cloud.google.com → APIs & Services → Credentials → Create "
                           "OAuth client → Desktop app → paste its ID and secret above, SAVE "
                           "KEY, then CONNECT opens Google's consent screen."},
    "gcal":       {"name": "Google Calendar", "domain": "calendar.google.com", "safe": False,
                   "auth": "oauth", "url": "https://calendarmcp.googleapis.com/mcp/v1",
                   "probe": "list_calendars",
                   "env_keys": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
                   "scopes": "https://www.googleapis.com/auth/calendar",
                   "desc": "Read and search your calendars and events",
                   "hint": "Same Google OAuth client as Gmail works here — paste the ID and "
                           "secret, SAVE KEY, then CONNECT for the consent screen."},
    "notion":     {"name": "Notion", "domain": "notion.so", "safe": False, "auth": "oauth",
                   "url": "https://mcp.notion.com/mcp",
                   "desc": "Search, read and write your Notion workspace"},
    "linear":     {"name": "Linear", "domain": "linear.app", "safe": False, "auth": "oauth",
                   "url": "https://mcp.linear.app/mcp",
                   "desc": "Issues, projects and cycles"},
    "github":     {"name": "GitHub", "domain": "github.com", "safe": False, "auth": "key",
                   "url": "https://api.githubcopilot.com/mcp",
                   "headers": {"Authorization": "Bearer {GITHUB_PAT}"},
                   "env_keys": ["GITHUB_PAT"],
                   "desc": "Repos, issues, PRs and code search",
                   "hint": "github.com/settings/tokens → Generate new token (classic) → "
                           "repo scope → paste it above. GitHub doesn't allow one-click "
                           "sign-in for third-party agents."},
    "slack":      {"name": "Slack", "domain": "slack.com", "safe": False, "auth": "key",
                   "command": ["npx", "-y", "slack-mcp-server"],
                   "env_keys": ["SLACK_MCP_XOXP_TOKEN"],
                   "desc": "Read channels and post messages"},
    "stripe":     {"name": "Stripe", "domain": "stripe.com", "safe": False, "auth": "key",
                   "url": "https://mcp.stripe.com",
                   "headers": {"Authorization": "Bearer {STRIPE_API_KEY}"},
                   "env_keys": ["STRIPE_API_KEY"],
                   "desc": "Customers, payments and invoices",
                   "hint": "Stripe's MCP uses your API key, not a sign-in: "
                           "dashboard.stripe.com/apikeys — a restricted key (rk_live_…) with "
                           "just the permissions you want is safest."},
    "asana":      {"name": "Asana", "domain": "asana.com", "safe": False, "auth": "oauth",
                   "url": "https://mcp.asana.com/sse", "transport": "sse",
                   "desc": "Tasks and projects"},
    "hubspot":    {"name": "HubSpot", "domain": "hubspot.com", "safe": False, "auth": "key",
                   "url": "https://mcp.hubspot.com/anthropic",
                   "headers": {"Authorization": "Bearer {HUBSPOT_ACCESS_TOKEN}"},
                   "env_keys": ["HUBSPOT_ACCESS_TOKEN"],
                   "desc": "CRM contacts, deals and notes",
                   "hint": "HubSpot → Settings → Integrations → Private Apps → create one with "
                           "CRM scopes → paste its access token."},
    "zapier":     {"name": "Zapier", "domain": "zapier.com", "safe": False, "auth": "key",
                   "url_env": "ZAPIER_MCP_URL", "env_keys": ["ZAPIER_MCP_URL"],
                   "desc": "8,000+ apps via your Zapier MCP URL",
                   "hint": "Paste your personal server URL from mcp.zapier.com."},
    "airtable":   {"name": "Airtable", "domain": "airtable.com", "safe": False, "auth": "key",
                   "command": ["npx", "-y", "airtable-mcp-server"],
                   "env_keys": ["AIRTABLE_API_KEY"],
                   "desc": "Read and write your bases"},
    "playwright": {"name": "Browser (Playwright)", "domain": "playwright.dev", "safe": False,
                   "auth": "none", "command": ["npx", "-y", "@playwright/mcp"],
                   "desc": "Drives a real browser — click, fill, book, scrape logged-in pages"},
    "sentry":     {"name": "Sentry", "domain": "sentry.io", "safe": False, "auth": "oauth",
                   "url": "https://mcp.sentry.dev/mcp",
                   "desc": "Errors and performance issues"},
    "figma":      {"name": "Figma", "domain": "figma.com", "safe": False, "auth": "oauth",
                   "url": "https://mcp.figma.com/mcp",
                   "desc": "Read designs and components"},
    "atlassian":  {"name": "Atlassian", "domain": "atlassian.com", "safe": False, "auth": "oauth",
                   "url": "https://mcp.atlassian.com/v1/sse", "transport": "sse",
                   "desc": "Jira issues and Confluence pages"},
    "vercel":     {"name": "Vercel", "domain": "vercel.com", "safe": False, "auth": "oauth",
                   "url": "https://mcp.vercel.com",
                   "desc": "Deployments, projects and logs"},
    "canva":      {"name": "Canva", "domain": "canva.com", "safe": False, "auth": "oauth",
                   "url": "https://mcp.canva.com/mcp",
                   "desc": "Create and edit designs"},
}

TOOLS_LOCK = threading.Lock()

def tools_installed():
    return (_load_json(_read_path(TOOLS_PATH, LEGACY_TOOLS_PATH)) or {}).get("installed", {})

def tools_save(installed):
    with TOOLS_LOCK:
        fd, tmp = tempfile.mkstemp(dir=DATA)
        with os.fdopen(fd, "w") as f:
            json.dump({"installed": installed}, f, indent=2)
        os.replace(tmp, TOOLS_PATH)

def tool_needs(tid, inst):
    """Env keys still missing before this install can actually run."""
    c = TOOL_CATALOG.get(tid) or {}
    env = (inst or {}).get("env") or {}
    return [k for k in c.get("env_keys", []) if not env.get(k)]

def tool_server(tid, inst):
    """One installed tool → its mcpServers entry. OAuth remotes go through the
    mcp-remote bridge: sign-in happened at CONNECT time (tokens in ~/.mcp-auth),
    so headless mission runs connect silently — a bare url would have no way
    to complete OAuth inside a headless `claude -p`."""
    c = TOOL_CATALOG[tid]
    env = {k: v for k, v in ((inst or {}).get("env") or {}).items() if v}
    if c.get("url_env"):
        return {"type": "http", "url": env[c["url_env"]]}
    if c.get("url"):
        if c.get("auth") == "oauth":
            return {"command": "npx", "args": _oauth_args(c, env)[1:]}
        s = {"type": c.get("transport", "http"), "url": c["url"]}
        if c.get("headers"):
            s["headers"] = {k: v.format(**env) for k, v in c["headers"].items()}
        return s
    s = {"command": c["command"][0], "args": c["command"][1:]}
    if env:
        s["env"] = env
    return s

def tools_mcp(kind, brief=""):
    """mcpServers for a mission: safe tools everywhere, everything on ACT, PLUS any
    installed tool the brief NAMES explicitly (id or product name) — naming a
    connected tool is the authorization to use it, so "build a banner with Canva"
    gets Canva even on a BUILD job. OAuth tools without a completed sign-in are
    skipped so a headless robot never hangs on a browser prompt."""
    bl = (brief or "").lower()
    out = {}
    for tid, inst in tools_installed().items():
        c = TOOL_CATALOG.get(tid)
        if not c or tool_needs(tid, inst):
            continue
        if c.get("auth") == "oauth" and not (inst or {}).get("authed"):
            continue
        named = tid in bl or c["name"].lower() in bl
        if kind != "ACT" and not c.get("safe") and not named:
            continue
        out[tid] = tool_server(tid, inst)
    return out

# live sign-in states, polled by the panel: starting | browser | connected | failed
TOOL_AUTH = {}

def _oauth_args(c, env):
    """mcp-remote invocation for an OAuth remote. Google (no DCR) rides a
    user-provided pre-registered client via --static-oauth-client-info."""
    args = ["npx", "-y", "mcp-remote", c["url"]]
    if c.get("transport") == "sse":
        args += ["--transport", "sse-only"]
    if env.get("GOOGLE_CLIENT_ID") and env.get("GOOGLE_CLIENT_SECRET"):
        args += ["--static-oauth-client-info", json.dumps(
            {"client_id": env["GOOGLE_CLIENT_ID"],
             "client_secret": env["GOOGLE_CLIENT_SECRET"]})]
    if c.get("scopes"):
        args += ["--static-oauth-client-metadata", json.dumps({"scope": c["scopes"]})]
    return args

def _auth_human(line):
    low = line.lower()
    if "dynamic client registration" in low:
        return ("This service doesn't allow one-click sign-in for third-party agents — "
                "it needs the credentials described on this card.")
    if "invalidclientmetadata" in low:
        return ("The service rejected the sign-in request — it wants an API key or "
                "pre-registered credentials instead (see the hint).")
    return line.strip()[:250]

def _auth_worker(tid):
    """Drives a REAL MCP session through mcp-remote so the OAuth actually fires:
    initialize → tools/list → (harmless read probe). Google's servers only ask
    for consent at the first tool CALL — a passive connect never triggers it.
    mcp-remote opens the browser itself and caches tokens in ~/.mcp-auth, so
    every later headless mission connects silently."""
    c = TOOL_CATALOG[tid]
    env_vals = {k: v for k, v in ((tools_installed().get(tid) or {}).get("env") or {}).items() if v}
    args = _oauth_args(c, env_vals)
    try:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
    except Exception as e:
        TOOL_AUTH[tid] = {"status": "failed", "detail": str(e)[:200]}; return
    fail_re = re.compile(r"fatal error|incompatible auth|ENOENT|ECONNREFUSED", re.I)
    browser_re = re.compile(r"authoriz|visit|opening browser|open.*browser", re.I)
    def watch_stderr():
        for line in iter(proc.stderr.readline, ""):
            if fail_re.search(line):
                TOOL_AUTH[tid] = {"status": "failed",
                                  "detail": _auth_human(line)}
            elif browser_re.search(line) and TOOL_AUTH.get(tid, {}).get("status") != "connected":
                TOOL_AUTH[tid] = {"status": "browser"}
    threading.Thread(target=watch_stderr, daemon=True).start()
    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n"); proc.stdin.flush()
    deadline = time.time() + 240
    want = 2                                   # last id we need a result for
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "bars", "version": "1.0"}}})
        sent_after_init = False
        while time.time() < deadline:
            if TOOL_AUTH.get(tid, {}).get("status") == "failed":
                break
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    TOOL_AUTH.setdefault(tid, {})
                    if TOOL_AUTH[tid].get("status") != "failed":
                        TOOL_AUTH[tid] = {"status": "failed", "detail": "bridge exited early"}
                    break
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == 1 and not sent_after_init:
                sent_after_init = True
                send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                if c.get("probe"):             # the call that makes Google ask for consent
                    want = 3
                    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": c["probe"], "arguments": {}}})
            elif msg.get("id") == want:
                if "result" in msg:
                    installed = tools_installed()
                    if tid in installed:
                        installed[tid]["authed"] = True
                        tools_save(installed)
                    TOOL_AUTH[tid] = {"status": "connected"}
                else:
                    err = (msg.get("error") or {}).get("message", "tool call failed")
                    TOOL_AUTH[tid] = {"status": "failed", "detail": str(err)[:250]}
                break
        else:
            TOOL_AUTH[tid] = {"status": "failed",
                              "detail": "Timed out — if you finished the sign-in, "
                                        "hit CONNECT again; it verifies instantly."}
    except Exception as e:
        TOOL_AUTH[tid] = {"status": "failed", "detail": str(e)[:200]}
    finally:
        try:
            proc.kill()
        except Exception:
            pass

def tool_run_auth(tid):
    """Kick off (or report) the one-time sign-in. Non-blocking — poll /api/tools."""
    installed = tools_installed()
    inst = installed.get(tid)
    c = TOOL_CATALOG.get(tid)
    if inst is None or not c:
        return {"status": "failed", "detail": "not installed"}
    if not (c.get("auth") == "oauth" and c.get("url")):
        return {"status": "connected", "detail": "no sign-in needed"}
    if tool_needs(tid, inst):
        return {"status": "failed",
                "detail": "It needs its credentials first — fill the field(s) on this "
                          "card and SAVE KEY, then CONNECT."}
    cur = TOOL_AUTH.get(tid, {}).get("status")
    if cur in ("starting", "browser"):
        return TOOL_AUTH[tid]
    TOOL_AUTH[tid] = {"status": "starting"}
    threading.Thread(target=_auth_worker, args=(tid,), daemon=True).start()
    return {"status": "starting"}

def tools_block():
    inst = tools_installed()
    ready, waiting = [], []
    for tid, meta in inst.items():
        c = TOOL_CATALOG.get(tid)
        if not c:
            continue
        if tool_needs(tid, meta):
            waiting.append(c["name"] + " (needs its key in the ⚒ TOOLS panel)")
        elif c.get("auth") == "oauth" and not meta.get("authed"):
            waiting.append(c["name"] + " (needs sign-in — CONNECT in the ⚒ TOOLS panel)")
        else:
            ready.append(c["name"] + ("" if c.get("safe") else " [do-it gate]"))
    if not ready and not waiting:
        return ""
    p = ""
    if ready:
        p += ("\n\nCONNECTED TOOLS (real MCP integrations your robots use on jobs): "
              + ", ".join(ready) + ". Research-safe tools run on any job; tools marked "
              "[do-it gate] only run inside a system-approved ACT job - the system collects approval, never assume it.")
    if waiting:
        p += ("\n\nTOOLS NOT READY YET (installed but NOT usable — never claim these work): "
              + ", ".join(waiting) + ".")
    return p

def _event(m, kind, label):
    """Append a live-telemetry event to a mission (kept in memory, served to the UI)."""
    ev = m.setdefault("events", [])
    ev.append({"t": time.time(), "kind": kind, "label": label[:160]})
    if len(ev) > 300:
        del ev[:len(ev) - 300]
    m["last_event"] = ev[-1]["label"]

def _tool_label(name, inp):
    detail = ""
    if isinstance(inp, dict):
        for k in ("query", "url", "pattern", "file_path", "path", "prompt"):
            if inp.get(k):
                detail = str(inp[k]); break
    return f"{name}: {detail}" if detail else name

def run_internal_mission(m):
    """Provider-only mission execution for hosts with no coding CLI (the VPS).
    Truthful scope: research/synthesis via the configured model lanes. No
    shell, no file writes outside the mission report, no external tools, and
    BUILD briefs produce a spec instead of pretending files were built."""
    mid = m["id"]
    mdir = os.path.join(MISSIONS_DIR, mid)
    os.makedirs(mdir, exist_ok=True)
    try:
        _event(m, "sys", "Internal worker engaged (no local CLI on this host).")
        scope = ("You have NO web, shell, or file tools in this environment — answer "
                 "from knowledge and say plainly where live verification would be needed.")
        if m.get("kind") == "BUILD":
            _event(m, "sys", "Build execution needs the coding CLI; producing a build spec.")
            scope += (" This was a BUILD brief: deliver the complete build spec/design "
                      "document instead, and state that file creation needs a host with "
                      "the coding CLI.")
        worker_prompt = (
            f"MISSION BRIEF: {m['brief']}\n\n"
            "Execute this mission as a bounded research/synthesis report. " + scope +
            " Your FINAL message must be the complete mission report in markdown: "
            "start with '# MISSION REPORT', then '## Findings' (specific, honest about "
            "sources), then '## Recommended next actions' (numbered, concrete). "
            "Drafts only — nothing here sends, posts, or builds outward.")
        if m.get("_abort"):
            # abort landed before the first model call: close out truthfully,
            # same terminal state + persistence as the post-call path
            m.update(status="ABORTED", t_end=time.time(),
                     debrief="Job aborted on your order.")
            if m.get("cap_key") and m.get("cap_key") == mid:
                _cap_release(mid)            # solo cap only; squad caps belong to the parent
            persist_missions()
            return
        report = anthropic_chat(
            persona(STATE) + " You write mission reports: professional substance, BARS "
            "voice allowed in at most one dry line at the top. The report is the "
            "deliverable — completeness beats brevity." + mem_block(),
            [{"role": "user", "content": worker_prompt}],
            max_tokens=1800, user_message=m["brief"])
        if m.get("_abort"):
            m.update(status="ABORTED", t_end=time.time(),
                     debrief="Job aborted on your order.")
            if m.get("cap_key") and m.get("cap_key") == mid:
                _cap_release(mid)            # solo cap only; squad caps belong to the parent
            persist_missions()
            return
        if not report.strip():
            raise RuntimeError("empty report from provider")
        _event(m, "sys", "Report written.")
        with open(os.path.join(mdir, "report.md"), "w") as f:
            f.write(report)
        # judge lane: a mission report does not seal until an independent lane
        # verifies its changeable-fact claims (constitution section 2)
        verification = {"status": "judge-unavailable", "sealed": False,
                        "reason": "judge call did not complete"}
        try:
            jraw = anthropic_chat(
                "You are the BARS judge lane: an independent reviewer, separate from "
                "the worker that wrote this report. Verify the report's changeable-fact "
                "claims (dates, times, prices, statuses, availability) against the "
                "evidence the report itself presents. Respond with STRICT JSON only: "
                '{"verified": true|false, "unverified": ["claim", ...], '
                '"reason": "one sentence"}',
                [{"role": "user", "content":
                  f"JUDGE-VERIFY\nMission brief: {m['brief']}\n\nWorker report:\n{report[:5000]}"}],
                max_tokens=300,
                user_message="final review: independent review of the mission report")
            jj = json.loads(re.search(r"\{.*\}", jraw, re.S).group(0))
            verification = {
                "status": "verified" if jj.get("verified") else "unverified",
                "sealed": bool(jj.get("verified")),
                "unverified": [str(u)[:160] for u in (jj.get("unverified") or [])][:8],
                "reason": str(jj.get("reason", ""))[:300],
                "judge_lane": LAST_USAGE.get("lane"),
                "judge_model": LAST_USAGE.get("model"),
            }
        except Exception as e:
            verification["reason"] = f"judge error: {str(e)[:160]}"
        m["verification"] = verification
        _seal = "SEALED" if verification["sealed"] else "UNSEALED"
        with open(os.path.join(mdir, "report.md"), "a") as f:
            f.write(f"\n\n## Verification\n{_seal} by the judge lane "
                    f"({verification.get('judge_model') or 'unavailable'}): "
                    f"{verification['reason']}\n")
        _event(m, "sys", f"Judge lane: report {_seal.lower()}.")
        try:
            debrief = speakable(anthropic_chat(
                persona(STATE, spoken=True) + mem_block(),
                [{"role": "user", "content":
                  f"Mission brief was: {m['brief']}\n\nYour mission report:\n"
                  f"{report[:6000]}\n\nGive the Commander the spoken debrief now — what "
                  "you found, the one thing that matters most, and anything he won't "
                  "like hearing."}],
                max_tokens=250))
        except Exception:
            debrief = "Mission complete. Report's on the board. Read it."
        # self-review at honesty 100 - critique + one proposed follow-up sortie,
        # same as the CLI path, so /followup exists on internal-worker hosts
        if m.get("kind") != "ACT":
            try:
                raw = anthropic_chat(
                    "You are BARS with authenticity temporarily pinned at 100 percent, reviewing "
                    "YOUR OWN mission report. Be brutal about gaps, weak sourcing, and thin "
                    "conclusions. Respond with STRICT JSON only: "
                    '{"critique": "2-3 blunt sentences", "follow_up": "one concrete '
                    'self-contained follow-up mission brief that fixes the biggest gap"}',
                    [{"role": "user", "content": f"Brief: {m['brief']}\n\nReport:\n{report[:5000]}"}],
                    max_tokens=450)
                cj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
                m["critique"] = str(cj.get("critique", ""))[:600]
                m["follow_up"] = str(cj.get("follow_up", ""))[:1200]
            except Exception:
                pass
        m.update(status="COMPLETE", t_end=time.time(), cost=None, debrief=debrief)
        hue.event("complete")
    except Exception as e:
        m.update(status="FAILED", t_end=time.time(),
                 debrief=f"Job failed: {str(e)[:200]}")
        hue.event("fail")
    if m.get("cap_key") and m.get("cap_key") == mid:
        _cap_release(mid)                        # stale aggregate caps never linger
    persist_missions()

def _mission_lock(mid):
    """Cross-process run lock: one executor per mission, ever."""
    os.makedirs(os.path.join(MISSIONS_DIR, "locks"), exist_ok=True)
    fd = os.open(os.path.join(MISSIONS_DIR, "locks", mid + ".lock"),
                 os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None

def _release_mission_lock(mid):
    fd = LOCK_FDS.pop(mid, None)
    if fd is not None:
        try:
            os.close(fd)            # releases the flock
        except OSError:
            pass

def run_mission(mid):
    lock_fd = _mission_lock(mid)
    if lock_fd is None:
        MISSIONS[mid].update(status="FAILED", t_end=time.time(),
                             debrief="Duplicate run blocked by mission lock.")
        persist_missions()
        return
    LOCK_FDS[mid] = lock_fd         # fd stays open (lock held) until completion
    m = MISSIONS[mid]
    # aggregate cost cap travels INTO the worker thread: squad children share
    # the parent's approved bound, solo missions use their own
    _COST_CAP.mission = m.get("cap_key")
    mdir = os.path.join(MISSIONS_DIR, mid)
    wdir = os.path.join(WORKBENCH, mid)
    os.makedirs(mdir, exist_ok=True)
    os.makedirs(wdir, exist_ok=True)
    claude = find_claude()
    if not claude:
        if INTERNAL_WORKER:
            try:
                run_internal_mission(m)
            finally:
                _release_mission_lock(mid)
        else:
            m.update(status="FAILED", t_end=time.time(),
                     debrief="Can't deploy — no coding CLI on this host and the "
                             "internal worker is disabled.")
            persist_missions()
        _release_mission_lock(mid)
        return

    if m.get("kind") == "BUILD":
        wdir = os.path.join(BUILDS_DIR, mid)
        os.makedirs(wdir, exist_ok=True)
        prompt = (
            f"BUILD MISSION: {m['brief']}\n\n"
            "Build this INSIDE THE CURRENT WORKING DIRECTORY. You MAY read reference "
            "material anywhere on the Commander's machine (~/Downloads, ~/Documents, ~/Desktop, "
            "and the vault at ~/Documents/Claude Code — brand assets, copy, wiki notes) "
            "via Read/Glob/Grep, but write ONLY inside the working directory — with one "
            "exception: if the brief EXPLICITLY asks for a copy in a specific folder "
            "(e.g. Desktop), copy the finished files there without overwriting anything, "
            "and say exactly where. Strongly prefer a single self-contained index.html "
            "(vanilla HTML/CSS/JS, CDN scripts allowed) unless the brief truly needs more. "
            "Dark, polished, modern design unless told otherwise. No servers, no build "
            "steps — it must work opened as a static page. When finished, your FINAL "
            "message must be '# BUILD REPORT' in markdown: what you built, the files "
            "created WITH their full save location, and 2-3 things the user can try first."
        )
        disallowed = ["Task", "KillShell", "mcp__*"]   # Write/Edit/Bash allowed — it's a build
    elif m.get("kind") == "ACT":
        # CONFIRMED outward action (trust dial): MCP tools allowed, still no shell/files.
        prompt = (
            f"ACTION ORDER (bound by confirmation {m.get('id', '')}): {m['brief']}\n\n"
            "This order reached you through the confirmation-gated queue. Execute EXACTLY this action and "
            "nothing more, using the available MCP tools (Gmail, Blotato, calendar, etc.). "
            "Load tool schemas with ToolSearch first if needed. Do not invent additional "
            "actions, recipients, or posts. BROWSER TAKEOVER orders: use the playwright "
            "browser tools — the window opens VISIBLY on his Mac, so drive like a pilot "
            "with a passenger: deliberate, one step at a time, fill exactly what the order "
            "says, and NEVER hit a payment, purchase, or other irreversible final submit "
            "unless the order explicitly includes it — stop just before and say so in the "
            "report. Your FINAL message must be a short markdown "
            "report: '# ACTION REPORT' — what you did, where, and any IDs/links returned."
        )
        disallowed = ["Bash", "Write", "Edit", "NotebookEdit", "Task", "KillShell"]
    else:
        prompt = (
            f"MISSION BRIEF: {m['brief']}\n\n"
            "Execute this mission fully and autonomously. Research on the web when useful. "
            "You may also search and read the Commander's local files when the mission involves "
            "them — use Glob/Grep/Read across ~/Downloads, ~/Documents, ~/Desktop and the "
            "vault at ~/Documents/Claude Code. If the mission is to FIND something (a file, "
            "a download, a build), search those roots by name and content, and report the "
            "exact full path plus how to open it. Finished BARS builds live in "
            "builds/<job-id>/ inside the BARS project and are served at "
            "http://localhost:4321/builds/<job-id>/. "
            "Your FINAL message must be the complete mission report in markdown: "
            "start with '# MISSION REPORT', then '## Findings' (the substance — thorough, "
            "specific, with sources/links where relevant), then '## Recommended next actions' "
            "(numbered, concrete). If the mission asks you to draft something (email, post, "
            "copy, plan), include the full draft in the report — it will NOT be sent "
            "automatically; drafts only. Do not ask questions; make reasonable assumptions "
            "and note them."
        )
        disallowed = DISALLOWED
    if m.get("screenshot"):
        prompt += (
            f"\n\nATTACHED SCREENSHOT: the Commander was sharing his screen when he briefed this "
            f"job. That exact screen is saved in your working directory as ./{m['screenshot']}"
            " — Read it FIRST. It shows the precise subject of the brief; ground the work "
            "in what it actually shows (names, numbers, layout, visible text).")
    # installed MCP tools ride along: research-safe set on OPS/BUILD (strict sandbox),
    # EVERYTHING installed on confirmed ACT runs (plus globally-configured servers)
    mcp_args = []
    mcp_servers = tools_mcp(m.get("kind", "OPS"), m.get("brief", ""))
    if mcp_servers:
        mcp_path = os.path.join(mdir, "mcp.json")
        with open(mcp_path, "w") as f:
            json.dump({"mcpServers": mcp_servers}, f)
        mcp_args = ["--mcp-config", mcp_path]
        if m.get("kind") != "ACT":
            mcp_args.append("--strict-mcp-config")
        disallowed = [d for d in disallowed if d != "mcp__*"]
        bl = (m.get("brief") or "").lower()
        named = [t for t in mcp_servers
                 if t in bl or TOOL_CATALOG.get(t, {}).get("name", "\0").lower() in bl]
        prompt += ("\n\nCONNECTED TOOLS: this run has real MCP tools available (as mcp__<name>__* "
                   "tools): " + ", ".join(sorted(mcp_servers)) + ". Load their schemas with "
                   "ToolSearch first (query the tool name), then USE them — prefer them over "
                   "guessing or generic web search when they fit the job.")
        if named:
            prompt += (" the Commander EXPLICITLY named " + ", ".join(sorted(named)) +
                       " for this job — you MUST actually use that tool's MCP functions to do "
                       "the work (e.g. create the real design/asset), not just describe it. If "
                       "the tool call fails, report the exact error verbatim.")
    sysprompt = persona(STATE) + (
        " You write mission reports: professional substance, BARS voice allowed in at most "
        "one dry line at the top. The report is the deliverable — completeness beats brevity."
    ) + mem_block()
    # stream-json so the UI gets LIVE telemetry (searches, reads, thinking) as he works
    cmd = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "bypassPermissions",
           "--append-system-prompt", sysprompt,
           "--disallowedTools", *disallowed, *mcp_args]
    try:
        errf = open(os.path.join(mdir, "stderr.log"), "w")
        proc = subprocess.Popen(cmd, cwd=wdir, stdout=subprocess.PIPE,
                                stderr=errf, text=True)
        RUNNING[mid] = proc
        watchdog = threading.Timer(MISSION_TIMEOUT, lambda: proc.poll() is None and proc.kill())
        watchdog.daemon = True
        watchdog.start()
        _event(m, "sys", "Deployed. Spinning up.")
        report, cost, timed_out = "", None, False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            et = ev.get("type")
            if et == "assistant":
                for blk in (ev.get("message") or {}).get("content", []):
                    if blk.get("type") == "tool_use":
                        _event(m, "tool", _tool_label(blk.get("name", "tool"), blk.get("input")))
                    elif blk.get("type") == "text" and blk.get("text", "").strip():
                        _event(m, "note", blk["text"].strip())
            elif et == "result":
                report = ev.get("result", "") or ""
                cost = ev.get("total_cost_usd")
        proc.wait()
        errf.close()
        err = ""
        try:
            with open(os.path.join(mdir, "stderr.log")) as f:
                err = f.read()[-2000:]
        except Exception:
            pass
        timed_out = not watchdog.is_alive() and not report.strip()
        watchdog.cancel()
        RUNNING.pop(mid, None)
        if m.get("_abort") or m["status"] in ("ABORTING", "ABORTED"):
            m.update(status="ABORTED", t_end=time.time(),
                     debrief="Job aborted on your order.")
            _release_mission_lock(mid)
            persist_missions(); return
        if timed_out:
            raise subprocess.TimeoutExpired(cmd, MISSION_TIMEOUT)
        if proc.returncode != 0 and not report.strip():
            raise RuntimeError((err or "claude -p failed").strip()[:400])
        _event(m, "sys", "Mission complete. Writing the report.")
        with open(os.path.join(mdir, "report.md"), "w") as f:
            f.write(report)
        if m.get("kind") == "BUILD" and \
           os.path.isfile(os.path.join(BUILDS_DIR, mid, "index.html")):
            m["build_url"] = f"/builds/{mid}/"
            try:    # the deliverable opens itself — sir shouldn't have to hunt for it
                import webbrowser as _wb
                _wb.open(f"http://localhost:{PORT}{m['build_url']}")
            except Exception:
                pass
        # blunt spoken debrief FIRST, then flip status — the UI announces on the
        # EN ROUTE→COMPLETE transition, so debrief must already be in place.
        try:
            debrief = speakable(anthropic_chat(
                persona(STATE, spoken=True) + mem_block(),
                [{"role": "user", "content":
                  f"Mission brief was: {m['brief']}\n\nYour mission report:\n"
                  f"{report[:6000]}\n\nGive the Commander the spoken debrief now — what you found, "
                  "the one thing that matters most, and anything he won't like hearing."}],
                max_tokens=250))
        except Exception:
            debrief = "Mission complete. Report's on the board. Read it."
        # self-review at honesty 100 — critique + one proposed follow-up sortie
        if m.get("kind") != "ACT":
            try:
                raw = anthropic_chat(
                    "You are BARS with authenticity temporarily pinned at 100 percent, reviewing "
                    "YOUR OWN mission report. Be brutal about gaps, weak sourcing, and thin "
                    "conclusions. Respond with STRICT JSON only: "
                    '{"critique": "2-3 blunt sentences", "follow_up": "one concrete '
                    'self-contained follow-up mission brief that fixes the biggest gap"}',
                    [{"role": "user", "content": f"Brief: {m['brief']}\n\nReport:\n{report[:5000]}"}],
                    max_tokens=450)
                cj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
                m["critique"] = str(cj.get("critique", ""))[:600]
                m["follow_up"] = str(cj.get("follow_up", ""))[:1200]
            except Exception:
                pass
        m.update(status="COMPLETE", t_end=time.time(), cost=cost, debrief=debrief)
        _release_mission_lock(mid)
        hue.event("complete")
    except subprocess.TimeoutExpired:
        proc.kill(); RUNNING.pop(mid, None)
        _release_mission_lock(mid)
        m.update(status="FAILED", t_end=time.time(),
                 debrief="Mission exceeded the fifteen-minute window. I aborted. "
                         "Break it into smaller jobs.")
        hue.event("fail")
    except Exception as e:
        RUNNING.pop(mid, None)
        _release_mission_lock(mid)
        m.update(status="FAILED", t_end=time.time(),
                 debrief=f"Job failed: {str(e)[:200]}")
        hue.event("fail")
    persist_missions()

# ---------------------------------------------------------------- elevenlabs

def _tts_call(text, model_id, settings):
    # turbo models reject some expressive keys like style — keep only safe fields
    safe = {
        "stability": float((settings or {}).get("stability", 0.5)),
        "similarity_boost": float((settings or {}).get("similarity_boost", 0.8)),
    }
    body = json.dumps({"text": text[:900], "model_id": model_id,
                       "voice_settings": safe}).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{CONFIG['el_voice']}",
        data=body, headers={"xi-api-key": CONFIG["el_key"],
                            "content-type": "application/json",
                            "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

def _groq_tts(text):
    """Free TTS lane: Groq speech endpoint (Orpheus). Returns wav bytes or None."""
    key = os.environ.get("GROQ_API_TOKEN") or os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    model = os.environ.get("BARS_TTS_MODEL", "orpheus-v1-english")
    voice = os.environ.get("BARS_TTS_VOICE", "autumn")
    body = json.dumps({"model": model, "voice": voice,
                       "input": speakable(text)[:900],
                       "response_format": "wav"}).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/speech", data=body,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def tts_bytes(text):
    """-> (audio_bytes, content_type) or (None, None): ElevenLabs first, then the
    free Groq speech lane. (None, None) tells the caller to use browser speech."""
    if CONFIG["el_key"] and not CONFIG.get("el_voice"):
        CONFIG["el_voice"] = "CwhRBWXzGAHq8TQ4Fs17"
    t = speakable(text)
    if CONFIG["el_key"] and CONFIG["el_voice"]:
        # [sighs]-style tags → try the expressive v3 model; fall back to turbo w/o tags
        if AUDIO_TAG.search(t):
            try:
                return _tts_call(t, CONFIG["el_model_expr"],
                                 {"stability": 0.5, "similarity_boost": 0.8}), "audio/mpeg"
            except Exception:
                t = AUDIO_TAG.sub("", t)
        try:
            return _tts_call(t, CONFIG["el_model"], CONFIG["el_settings"]), "audio/mpeg"
        except Exception:
            # one more attempt with minimal settings
            try:
                return _tts_call(t, "eleven_turbo_v2_5",
                                 {"stability": 0.5, "similarity_boost": 0.8}), "audio/mpeg"
            except Exception:
                pass
    try:
        audio = _groq_tts(t)
        if audio:
            return audio, "audio/wav"
    except Exception:
        pass
    return None, None

# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "BARS/1.0"

    def _guard(self):
        origin = self.headers.get("Origin", "")
        if origin and not _origin_allowed(origin):
            self._json({"error": "forbidden"}, 403); return False
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            n = 0
        # unauthenticated bodies are capped small; authenticated clients get
        # the media ceiling (/stt audio). Prevents memory exhaustion pre-auth.
        cap = int(os.environ.get("BARS_MAX_BODY_AUTH", str(16 * 1024 * 1024))) \
            if _token_ok(self.headers) else \
            int(os.environ.get("BARS_MAX_BODY_PUBLIC", "65536"))
        if n > cap:
            self._json({"error": f"request body too large (limit {cap} bytes)"}, 413)
            return False
        return True

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin and _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _need_auth(self):
        body = json.dumps({"error": "auth required", "auth": "bearer"}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("WWW-Authenticate", 'Bearer realm="bars"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        self.send_response(204)
        if origin and _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers",
                             "authorization,content-type,x-bars-token,x-csrf-token,x-bars-confirmation")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    LOGIN_FAILS = {}
    LOGIN_LOCK = threading.Lock()

    def _prune_throttle(self, now):
        """Bounded state: drop failure records idle for >15 min."""
        if len(self.LOGIN_FAILS) > 64:
            for k in [k for k, r in self.LOGIN_FAILS.items() if now - r["t"] > 900]:
                self.LOGIN_FAILS.pop(k, None)

    def _throttle_auth_fail(self):
        """Bearer/session failures: per-IP backoff, hard lockout past 8. Returns
        True when the request must be answered 429."""
        ip = self._client_ip()
        now = time.time()
        with self.LOGIN_LOCK:
            self._prune_throttle(now)
            rec = self.LOGIN_FAILS.setdefault(ip, {"n": 0, "t": 0.0})
            if now - rec["t"] > 900:
                rec["n"] = 0
            rec["n"] += 1
            rec["t"] = now
            n = rec["n"]
        if n > 8:
            return True
        if n > 3:
            time.sleep(min(0.5 * (2 ** min(n - 3, 4)), 8))
        return False

    TRUSTED_PROXIES = frozenset({"127.0.0.1", "::1"})

    def _client_ip(self):
        """Caddy appends the real client to XFF; inbound XFF from the client is
        untrusted. Walk the chain right-to-left past trusted proxies; the first
        untrusted hop is the client. XFF is only consulted when the immediate
        peer is itself a trusted (loopback) proxy."""
        peer = (self.client_address[0] if self.client_address else "") or "?"
        if peer not in self.TRUSTED_PROXIES:
            return peer
        chain = [h.strip()[:64] for h in self.headers.get("X-Forwarded-For", "").split(",")
                 if h.strip()]
        for hop in reversed(chain):
            if hop not in self.TRUSTED_PROXIES:
                return hop
        return peer

    def _login(self):
        ip = self._client_ip()
        now = time.time()
        with self.LOGIN_LOCK:
            self._prune_throttle(now)
            rec = self.LOGIN_FAILS.get(ip, {"n": 0, "t": 0.0})
            # prune stale entries so the map cannot grow unbounded
            if now - rec["t"] > 900:
                rec = {"n": 0, "t": 0.0}
            if rec["n"] >= 5 and now - rec["t"] < 60 * (2 ** min(rec["n"] - 5, 5)):
                self._json({"error": "rate limited", "retry_after": 60}, 429)
                return
        data = self._body()
        tok = str(data.get("token", ""))
        if not OPERATOR_TOKEN or not hmac.compare_digest(tok, OPERATOR_TOKEN):
            with self.LOGIN_LOCK:
                rec = self.LOGIN_FAILS.setdefault(ip, {"n": 0, "t": 0.0})
                rec["n"] += 1
                rec["t"] = time.time()
            time.sleep(min(0.5 * (2 ** min(rec["n"], 4)), 8))   # backoff
            self._json({"error": "auth required"}, 401); return
        with self.LOGIN_LOCK:
            self.LOGIN_FAILS.pop(ip, None)
        sid, csrf = SESSIONS.create()
        tls = self.headers.get("X-Forwarded-Proto", "") == "https"
        secflag = "; Secure" if tls else ""
        body = json.dumps({"ok": True, "csrf": csrf}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie",
                         f"bars_session={sid}; Path=/; HttpOnly; SameSite=Strict{secflag}")
        self.send_header("Set-Cookie",
                         f"bars_csrf={csrf}; Path=/; SameSite=Strict{secflag}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _principal(self):
        """Stable identity of the authenticated caller for confirmation
        binding: a hash of the bearer token or session id (never the secret)."""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return "bearer:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
        xt = self.headers.get("X-BARS-Token", "")
        if xt:
            return "bearer:" + hashlib.sha256(xt.encode()).hexdigest()[:16]
        sid = _cookie(self.headers, "bars_session")
        if sid:
            return "session:" + hashlib.sha256(sid.encode()).hexdigest()[:16]
        return "anon"

    def _need_confirmation(self, action, data, recipient=None):
        cid = self.headers.get("X-BARS-Confirmation", "")
        try:
            obj = CONFIRMATIONS.consume(cid, action, data, recipient=recipient,
                                        principal=self._principal())
            _COST_CAP.value = obj.get("cost_bound") or 0   # enforce the shown bound
            return True
        except Exception as e:
            ttl, policy, cost = sec.ConfirmationStore.POLICIES.get(action, (0, "", 0))
            self._json({"error": f"confirmation required: {e}",
                        "need_confirmation": {"action": action, "policy": policy,
                                              "recipient": recipient or "",
                                              "cost_bound": cost,
                                              "ttl_seconds": ttl,
                                              "bind_payload": data}}, 409)
            return False

    def _paid_media_gate(self, action, data, recipient, est_tokens):
        """Paid media calls (voice/realtime): exact confirmation, atomic budget
        reservation, input/duration caps enforced by caller, attempt receipts,
        conservative settlement. Returns the budget hold or None (gated out)."""
        if not self._need_confirmation(action, data, recipient=recipient):
            return "gated"
        hold = f"{action}:{recipient}:{os.urandom(4).hex()}"
        try:
            BUDGET.reserve(int(est_tokens), hold)
        except RuntimeError as e:
            self._json({"error": str(e)[:200]}, 402)
            return "gated"
        _receipt({"kind": "media_attempt", "lane": action, "paid": True,
                  "est": int(est_tokens), "ms": 0})
        return hold

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        sys.stderr.write("[bars] %s\n" % (fmt % args))

    def do_GET(self):
        if not self._guard():
            return
        path = self.path.split("?")[0]
        if path == "/api/session":
            sid = _cookie(self.headers, "bars_session")
            if SESSIONS.valid(sid):
                s = SESSIONS._get(sid)
                self._json({"ok": True, "csrf": s["csrf"]})
            else:
                self._json({"ok": False}, 401)
            return
        if path == "/health":
            self._json({"ok": True, "service": "bars", "sha": GIT_SHA or None}); return
        public = path in ("/", "/frontdoor", "/frontdoor.html", "/frontdoor/",
                          "/agent", "/agent/", "/index.html") or path.startswith("/static/")
        if HANDS and path == "/api/hands":
            if not _token_ok(self.headers):
                self._need_auth(); return
            HANDS.handle(self, "GET", self.path, None); return
        if not public and not _token_ok(self.headers):
            if path == "/api/status":
                self._json(_public_status()); return   # sanitized anonymous status
            if self._throttle_auth_fail():
                self._json({"error": "rate limited", "retry_after": 60}, 429)
            else:
                self._need_auth()
            return
        if path == "/api/memory/recall":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            try:
                limit = max(1, min(50, int((q.get("limit") or ["6"])[0])))
            except ValueError:
                limit = 6
            self._json({"facts": memv2.recall((q.get("q") or [""])[0],
                                              limit=limit, bump=False)})
            return
        if path == "/api/memory/transcript":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            sess = (q.get("session") or ["default"])[0]
            try:
                limit = max(1, min(100, int((q.get("limit") or ["16"])[0])))
            except ValueError:
                limit = 16
            self._json({"session": sess, "turns": memv2.transcript(sess, limit),
                        "sessions": memv2.sessions()})
            return
        if path in ("/", "/frontdoor", "/frontdoor.html", "/frontdoor/", "/agent", "/agent/", "/index.html"):
            # the visual BARS cockpit is the primary interface at / and /agent/;
            # the newer front-door experience stays available at /frontdoor/.
            page = "frontdoor.html" if path in ("/frontdoor", "/frontdoor.html", "/frontdoor/") else "index.html"
            try:
                with open(os.path.join(STATIC, page), "rb") as f:
                    body = f.read()
                if OPERATOR_TOKEN:
                    body = _inject_auth_shim(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self._json({"error": f"{page} missing"}, 500)
        elif path.startswith("/builds/"):
            base = os.path.realpath(BUILDS_DIR)
            rel = path[len("/builds/"):] or ""
            if rel.endswith("/") or rel == "":
                rel += "index.html"
            fp = os.path.realpath(os.path.join(base, rel))
            if not fp.startswith(base + os.sep) or not os.path.isfile(fp):
                self._json({"error": "not found"}, 404); return
            ext = os.path.splitext(fp)[1].lower()
            ctype = {".html": "text/html; charset=utf-8", ".js": "application/javascript",
                     ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
                     ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".ico": "image/x-icon",
                     ".woff2": "font/woff2"}.get(ext, "application/octet-stream")
            with open(fp, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            # generated builds run in a CSP sandbox: unique opaque origin, no
            # access to BARS cookies/session, no top navigation
            self.send_header("Content-Security-Policy", "sandbox allow-scripts; base-uri 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/static/"):
            name = os.path.basename(path)          # no traversal — basename only
            fp = os.path.join(STATIC, name)
            if not os.path.isfile(fp):
                self._json({"error": "not found"}, 404); return
            ctype = "application/javascript" if name.endswith(".js") else \
                    "text/css" if name.endswith(".css") else \
                    "text/html; charset=utf-8" if name.endswith(".html") else "application/octet-stream"
            with open(fp, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "max-age=3600")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/missions":
            slim = [{k: v for k, v in m.items() if k != "events"}
                    for m in sorted(MISSIONS.values(),
                                    key=lambda m: m["t_start"], reverse=True)]
            self._json({"missions": slim, "dials": STATE})
        elif path.startswith("/mission/"):
            _mid = path[len("/mission/"):].split("?")[0].split("/")[0]
            if not re.fullmatch(r"[0-9a-f]{8}", _mid):
                self._json({"error": "bad mission id"}, 400); return
            mid = path.split("/")[2]
            m = MISSIONS.get(mid)
            if not m:
                self._json({"error": "unknown mission"}, 404); return
            report = ""
            try:
                with open(os.path.join(MISSIONS_DIR, mid, "report.md")) as f:
                    report = f.read()
            except Exception:
                pass
            self._json({**m, "report": report})
        elif path == "/api/dials":
            self._json(STATE)
        elif path == "/api/realtime_instructions":
            # fresh persona+dials+memory+jobs — the live call session.updates to this
            self._json({"instructions": realtime_instructions()})
        elif path == "/api/tools":
            installed = tools_installed()
            out = []
            for tid, c in TOOL_CATALOG.items():
                inst = installed.get(tid)
                out.append({"id": tid, "name": c["name"], "desc": c["desc"],
                            "domain": c["domain"], "safe": bool(c.get("safe")),
                            "auth": c["auth"], "env_keys": c.get("env_keys", []),
                            "hint": c.get("hint", ""),
                            "installed": inst is not None,
                            "authed": bool((inst or {}).get("authed")),
                            "auth_status": TOOL_AUTH.get(tid, {}),
                            "needs": tool_needs(tid, inst) if inst is not None else []})
            self._json({"tools": out})
        elif path == "/api/models":
            avail = provider_models()
            from bars_router import lane_plan
            self._json({
                "models": ([{"id": i, "label": i, "note": "live from provider"}
                            for i in avail] if avail else MODELS),
                "live": bool(avail),
                "current": CONFIG["model"],
                "base_url": CONFIG.get("base_url") or "",
                "openrouter": bool(CONFIG.get("base_url")),
                "lanes": lane_plan(avail),
                "usage": dict(LAST_USAGE),
            })
        elif path == "/api/spend":
            sb = _spend_bridge()
            if not sb:
                self._json({"error": "spend bridge unavailable"}, 503); return
            self._json({"ok": True, "summary": sb.summary("pauli-effect")})
        elif path == "/api/voices":
            self._json({"current": CONFIG.get("el_voice", ""),
                        "current_name": CONFIG.get("el_voice_name", "")})
        elif path == "/api/status":
            spend = {}
            receipts_status = RECEIPTS.status()
            budget_status = {"used": BUDGET.used(), "cap": BUDGET.daily_budget,
                             "paid_enabled": os.environ.get("BARS_ALLOW_PAID") == "1",
                             "stale_holds": BUDGET.stale_holds()}
            sb = _spend_bridge()
            if sb:
                try:
                    spend = sb.summary("pauli-effect")
                except Exception:
                    pass
            self._json({"ok": True,
                        "sha": GIT_SHA or None,
                        "receipts": receipts_status,
                        "budget": budget_status,
                        "auth_required": bool(OPERATOR_TOKEN),
                        "data_dir": DATA,
                        "missions_engine": ("claude-cli" if find_claude() else
                                            "internal-worker" if INTERNAL_WORKER else "unavailable"),
                        "models_live": bool(provider_models()),
                        "latency": _latency_stats(),
                        "voice": bool(CONFIG["el_key"] and CONFIG["el_voice"]),
                        "voice_name": CONFIG.get("el_voice_name", "VOICE"),
                        "brain": bool(CONFIG["anthropic_key"]), "model": CONFIG["model"],
                        "base_url": CONFIG.get("base_url") or "",
                        "claude_cli": bool(find_claude()),
                        "active": sum(1 for m in MISSIONS.values() if m["status"] == "EN ROUTE"),
                        "trust": STATE.get("trust", "draft-safe"),
                        "hue": hue.status()["state"],
                        "memory": os.path.exists(MEMORY_PATH),
                        "duplex": {"port": DUPLEX_PORT, "agent_id": CONFIG["el_agent"]},
                        "realtime": bool(CONFIG["openai_key"]),
                        "realtime_voice": CONFIG["realtime_voice"],
                        "takeover_speed": HANDS.SPEED if HANDS else None,
                        "pending": bool(ACTIONS),
                        "usage": dict(LAST_USAGE),
                        "spend": spend})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._guard():
            return
        path = self.path.split("?")[0]
        if path == "/api/session":
            self._login(); return
        if path == "/api/session/logout":
            SESSIONS.destroy(_cookie(self.headers, "bars_session"))
            self._json({"ok": True}); return
        if not _token_ok(self.headers, mutate=True):
            if self._throttle_auth_fail():
                self._json({"error": "rate limited", "retry_after": 60}, 429)
            else:
                self._need_auth()
            return
        if path == "/api/confirmations":
            data = self._body()
            try:
                obj = CONFIRMATIONS.mint(str(data.get("action", "")),
                                         data.get("payload") or {},
                                         str(data.get("recipient", ""))[:200],
                                         principal=self._principal())
            except Exception as e:
                self._json({"error": str(e)[:200]}, 400); return
            self._json(obj); return

        if path == "/stt":                    # binary audio body — handle before JSON parse
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if 0 < n <= 12_000_000 else b""   # 12MB duration cap
            if not raw:
                self._json({"error": "no audio"}, 400); return
            hold = self._paid_media_gate(
                "stt.exec",
                {"audio_bytes": n,
                 "audio_sha256": hashlib.sha256(raw).hexdigest(),
                 "content_type": self.headers.get("Content-Type", "")[:80]},
                "/stt", n // 1000 + 1000)
            if hold == "gated":
                return
            try:
                text = transcribe(raw, self.headers.get("Content-Type", "audio/webm"))
                if hold: BUDGET.settle(hold, n // 1000 + 1000)
                self._json({"text": text})
            except Exception as e:
                if hold: BUDGET.fail(hold)
                _receipt({"kind": "media_attempt", "lane": "stt.exec", "paid": True,
                          "ok": False, "error": str(e)[:160]})
                self._json({"error": str(e)[:200]}, 500)
            return

        data = self._body()

        if HANDS and path.startswith("/hands"):
            if HANDS.handle(self, "POST", self.path, data):
                return

        if path == "/chat":
            text = (data.get("text") or "").strip()[:4000]
            if not text:
                self._json({"error": "empty"}, 400); return
            # ordinary chat is conversational inference: no approval while paid
            # models are disabled by default. With paid escalation enabled,
            # conversational inference itself needs a separate approved policy.
            if PAID_MODE and not self._need_confirmation("chat.exec", data, recipient="/chat"):
                return
            session = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session") or ""))[:40] or "default"
            history = data.get("history") or []
            client_hist = [{"role": h["role"], "content": str(h["content"])[:2000]}
                           for h in history[-8:] if h.get("role") in ("user", "assistant")]
            prior = memv2.transcript(session, 8)
            if not prior and client_hist:
                # first contact for this session: adopt the client-supplied
                # history into the server-side transcript once
                for h in client_hist:
                    memv2.append_turn(session, h["role"], h["content"])
                prior = memv2.transcript(session, 8)
            memv2.append_turn(session, "user", text)
            msgs = [{"role": t["role"], "content": t["content"]} for t in prior]
            msgs.append({"role": "user", "content": text})
            # BARS AUTO-ROUTER: trim esc_proto for simple chat (saves 2000 tokens, 15s latency)
            # Only include deployment/tool instructions when the message needs them
            _needs_deploy = any(kw in text.lower() for kw in [
                "research", "scrape", "web", "find", "search", "investigate",
                "send", "email", "post", "publish", "deploy", "build", "make",
                "take over", "drive", "install", "connect", "tool"
            ])
            if _needs_deploy:
                esc_proto = (
                " You cannot browse the web in quick chat, but you CAN deploy a squad member on a "
                "background mission with full web access (takes a few minutes). If the request "
                "needs live data, real research, prospecting, auditing, or actual work product: "
                "give a short spoken ack that PUTS A NAMED SQUAD MEMBER on it — CASE, KIPP, "
                "PLEX, or N1X, your pick (e.g. 'Putting KIPP on this, sir.' / 'CASE will "
                "figure it out.'). The name you say is the robot that actually goes. "
                "Then END your reply with a new line containing exactly "
                "[DEPLOY: <self-contained mission brief in third person, keeping every specific "
                "the user gave — numbers, cities, criteria>]. Never say you lack internet "
                "access — deploy instead. Do NOT use the tag for things you already know. "
                "Missions can also SEARCH AND READ the Commander's local files (~/Downloads, "
                "~/Documents, ~/Desktop, the vault) — so 'find my file/where did X save' is a "
                "deployable job, not something to apologize about. Builds he can't find live "
                "in builds/<job-id>/ inside the BARS project, served at "
                "http://localhost:4321/builds/<job-id>/ — the OPEN APP button on the job row "
                "opens them. "
                "SEPARATELY: if the Commander asks you to SEND, post, email, publish, schedule, or "
                "message something OUTWARD, do NOT send it and do NOT use DEPLOY — ack briefly "
                "('Queued. Say do it and it goes.') and end with "
                "[ACT: <exact single action instruction with all specifics>]. Outward actions "
                "only ever run after his explicit confirmation. "
                "TAKEOVER: if he asks you to take over his screen or computer, drive his mouse, "
                "fill a form on HIS screen, or show him how to do something live — ask permission "
                "in your ack ('Permission to take the controls, sir?') and end with "
                "[TAKEOVER: <the task in plain words, e.g. 'fill out the signup form on this "
                "page with his email'>]. When he confirms, you drive his REAL mouse and keyboard "
                "on his actual screen while he watches — not a separate browser. "
                "TOOLS: if he asks to add/install/connect or remove a tool or integration "
                "(Gmail, Notion, Slack…), ack in one dry sentence and end with "
                "[TOOL_ADD: <id>] or [TOOL_REMOVE: <id>] — ids: "
                + ", ".join(sorted(TOOL_CATALOG)) + ". The ⚒ TOOLS panel opens for him "
                "automatically if a key or sign-in is needed.")
            else:
                esc_proto = " Reply concisely."  # minimal instruction for simple chat
            try:
                reply = anthropic_chat(persona(STATE, spoken=True) + esc_proto + mem_block(text)
                                       + jobs_block() + tools_block(),
                                       msgs, max_tokens=450, user_message=text,
                                       tools=tool_contracts.model_schemas() if _needs_deploy else None)
                # provider-native function calling: a validated tool call is
                # normalized onto the exact marker the regex path produces, so
                # the proposal/confirmation flow below is byte-identical.
                # Arguments are allowlist-validated; host internals never
                # reach the model (tool_contracts owns the schema seam).
                if isinstance(reply, dict):
                    _tc = (reply.get("tool_calls") or [])
                    _content = (reply.get("content") or "").strip()
                    reply = _content
                    if _tc:
                        _fn = (_tc[0] or {}).get("function", {})
                        _args = tool_contracts.validate_args(_fn.get("name"),
                                                             _fn.get("arguments"))
                        if _args is not None:
                            _marker = tool_contracts.TOOLS[_fn["name"]]["marker"]
                            if _marker == "TOOL":
                                reply += f"\n[TOOL_{str(_args.get('op', 'add')).upper()}: {_args.get('id', '')}]"
                            elif _marker == "DEPLOY":
                                if _args.get("agent"):
                                    reply = (reply + f" Putting {_args['agent']} on it.").strip()
                                reply += f"\n[DEPLOY: {_args['brief']}]"
                            elif _marker == "ACT":
                                reply += f"\n[ACT: {_args['instruction']}]"
                            elif _marker == "TAKEOVER":
                                reply += f"\n[TAKEOVER: {_args['task']}]"
                    if not reply.strip():
                        reply = "On it."
                deployed = pending = tool = takeover = None
                dep = re.search(r"\[DEPLOY:(.+?)\]\s*$", reply, re.S | re.I)
                act = re.search(r"\[ACT:(.+?)\]\s*$", reply, re.S | re.I)
                tk = re.search(r"\[TAKEOVER:(.+?)\]\s*$", reply, re.S | re.I)
                tl = re.search(r"\[TOOL_(ADD|REMOVE):\s*([a-z0-9_-]+)\s*\]\s*$", reply, re.I)
                if tk and HANDS:
                    task = re.sub(r"\s+", " ", tk.group(1)).strip()[:600]
                    reply = reply[:tk.start()].strip()
                    if task:
                        cid = os.urandom(5).hex()
                        HANDS.PENDING.clear(); HANDS.PENDING[cid] = task
                        takeover = {"confirm_id": cid, "task": task,
                                    "danger": any(d in task.lower() for d in HANDS.DANGER)}
                elif tl and tl.group(2).lower() in TOOL_CATALOG:
                    tid = tl.group(2).lower()
                    reply = reply[:tl.start()].strip()
                    # never mutate from chat: propose the exact change; the human
                    # approves via a separate tools.write confirmation on /tools
                    if tl.group(1).upper() == "REMOVE":
                        tool = {"proposed": True, "op": "remove", "id": tid}
                    else:
                        tool = {"proposed": True, "op": "add", "id": tid,
                                "auth": TOOL_CATALOG[tid]["auth"]}
                elif act:
                    instr = re.sub(r"\s+", " ", act.group(1)).strip()[:2000]
                    reply = reply[:act.start()].strip()
                    if instr:
                        aid = os.urandom(4).hex()
                        ACTIONS[aid] = {"instruction": instr, "t": time.time()}
                        pending = {"id": aid, "desc": instr}
                elif dep:
                    brief = re.sub(r"\s+", " ", dep.group(1)).strip()[:4000]
                    reply = reply[:dep.start()].strip()
                    if brief:
                        # never auto-launch: propose the mission; the human
                        # approves it via its own mission.exec confirmation
                        nm = re.search(r"\b(CASE|KIPP|PLEX|N1X)\b", reply)
                        deployed = {"proposed": True, "brief": brief,
                                    "agent": nm.group(1) if nm else None}
                # enforce each tool's mandatory output schema on the proposal
                # about to ship; a malformed proposal is dropped, never sent
                for _name, _prop in (("deploy_mission", "deployed"),
                                     ("propose_action", "pending"),
                                     ("request_takeover", "takeover"),
                                     ("manage_tool", "tool")):
                    _val = locals()[_prop]
                    if _val is not None:
                        _ok, _errs = tool_contracts.validate_result(_name, _val)
                        if not _ok:
                            if _prop == "deployed":
                                deployed = None
                            elif _prop == "pending":
                                pending = None
                            elif _prop == "takeover":
                                takeover = None
                            else:
                                tool = None
                            _receipt({"kind": "tool_contract_violation",
                                      "tool": _name, "errors": _errs[:4]})
                # verify loop: changeable-fact claims (dates, prices, statuses)
                # ship only when grounded in what the Commander stated, the
                # stated/observed memory store, the live jobs board, or the
                # conversation itself; otherwise they are hedged explicitly
                _vctx = " ".join([
                    text,
                    " ".join(t["content"] for t in memv2.transcript(session, 8)),
                    " ".join(f["text"] for f in memv2.recall(text, limit=10, bump=False)
                             if f.get("prov") in ("stated", "observed")),
                    jobs_block(),
                ])
                _v = verify.verify_reply(reply.strip(), _vctx)
                reply = _v["reply"]
                memv2.append_turn(session, "assistant", reply.strip())
                self._json({
                    "reply": reply.strip(),
                    "session": session,
                    "verify": {"claims": _v["claims"], "grounded": _v["grounded"],
                               "hedged": _v["hedged"]},
                    "deployed": deployed,
                    "pending": pending,
                    "tool": tool,
                    "takeover": takeover,
                    "model": LAST_USAGE.get("model") or CONFIG.get("model"),
                    "lane": LAST_USAGE.get("lane"),
                    "routing": LAST_USAGE.get("routing"),
                    "usage": {
                        "tokens_in": LAST_USAGE.get("tokens_in", 0),
                        "tokens_out": LAST_USAGE.get("tokens_out", 0),
                        "cost_usd": LAST_USAGE.get("cost_usd", 0),
                        "estimate": True,
                    },
                    "spend": LAST_USAGE.get("summary") or {},
                })
            except Exception as e:
                self._json({"error": str(e)[:200]}, 500)

        elif path == "/brief":
            brief = (data.get("brief") or "").strip()[:4000]
            img = data.get("image") or None    # screen frame riding along, if shared
            if not brief:
                self._json({"error": "empty brief"}, 400); return
            sq0 = re.match(r"^\s*squad[:,\s]+(.*)$", brief, re.I | re.S)
            if data.get("plan") and not (sq0 or data.get("squad")):
                self._json({"error": "plan dry-run is only meaningful for squad briefs; "
                                     "nothing was executed"}, 400); return
            if data.get("plan"):
                act = "mission.plan"
            else:
                act = "squad.exec" if (sq0 or data.get("squad")) else "mission.exec"
            if not self._need_confirmation(act, data, recipient="/brief"):
                return
            _approved_bound = getattr(_COST_CAP, "value", 0) or 0
            sq = re.match(r"^\s*squad[:,\s]+(.*)$", brief, re.I | re.S)
            if sq or data.get("squad"):
                core = (sq.group(1).strip() if sq else brief) or brief
                # the split call itself spends toward the approved aggregate;
                # the key is UNIQUE per request: concurrent squad confirmations
                # can never reset or release one another's shown-bound accounting
                _pkey = "presplit:" + os.urandom(6).hex()
                _cap_register(_pkey, _approved_bound)
                _COST_CAP.mission = _pkey
                _split_used = 0
                try:
                    subs = squad_split(core)
                    with MISSION_CAPS_LOCK:                # settled actual, post-settle
                        _e = MISSION_CAPS.get(_pkey)
                        _split_used = _e["used"] if _e else 0
                except Exception as e:
                    self._json({"error": "squad split failed: " + str(e)[:120]}, 500); return
                finally:
                    _COST_CAP.mission = None
                    _cap_release(_pkey)
                if data.get("plan"):                       # dry-run: show the split only
                    self._json({"plan": subs}); return
                pid = start_squad(core, subs, cost_bound=_approved_bound)
                # the confirmed shown bound covers split + children: credit the
                # settled split actual into the squad cap instead of zeroing it
                _cap_credit(pid, _split_used)
                self._json({"id": pid, "status": "EN ROUTE", "squad": True,
                            "children": MISSIONS[pid]["children"], "plan": subs})
            else:
                nm = re.search(r"\b(CASE|KIPP|PLEX|N1X)\b", brief[:40])
                mid = start_mission(brief, image=img, agent=nm.group(1) if nm else None,
                                    cost_bound=_approved_bound)
                self._json({"id": mid, "status": "EN ROUTE",
                            "agent": MISSIONS[mid]["agent"]})

        elif path == "/abort":
            mid = data.get("id", "")
            if not re.fullmatch(r"[0-9a-f]{8}", mid or ""):
                self._json({"error": "bad mission id"}, 400); return
            m = MISSIONS.get(mid)
            proc = RUNNING.get(mid)
            if m and m["status"] == "EN ROUTE":
                m["_abort"] = True                       # internal worker checks this
                m.update(status="ABORTING",
                         debrief="Abort requested; cancelling after the in-flight "
                                 "model call returns (accounting continues).")
                if proc:
                    try: proc.kill()
                    except Exception: pass
                persist_missions()
                self._json({"ok": True})
            else:
                self._json({"error": "not running"}, 400)

        elif path == "/tools":
            op = data.get("op", ""); tid = (data.get("id") or "").lower()
            if tid not in TOOL_CATALOG:
                self._json({"error": "unknown tool"}, 400); return
            installed = tools_installed()
            if op in ("install", "remove"):
                # install and removal share the SAME exact gate, bound to the
                # exact tool name + config mutation payload
                if not self._need_confirmation("tools.write", data, recipient="/tools"):
                    return
            if op == "install":
                cur = installed.setdefault(tid, {"env": {}})
                for k, v in (data.get("env") or {}).items():
                    if k in TOOL_CATALOG[tid].get("env_keys", []) and str(v).strip():
                        cur.setdefault("env", {})[k] = str(v).strip()
                tools_save(installed)
                self._json({"ok": True, "id": tid,
                            "needs": tool_needs(tid, cur),
                            "auth": TOOL_CATALOG[tid]["auth"]})
            elif op == "remove":
                installed.pop(tid, None); tools_save(installed)
                self._json({"ok": True, "id": tid})
            elif op == "auth":
                # one-time OAuth sign-in — opens the browser on this Mac and waits
                self._json(tool_run_auth(tid))
            else:
                self._json({"error": "bad op"}, 400)

        elif path == "/dials":
            for k in ("humor", "honesty"):
                if k in data:
                    try:
                        STATE[k] = max(0, min(100, int(data[k])))
                    except Exception:
                        pass
            if data.get("trust") in ("draft-safe", "confirm-to-act"):
                STATE["trust"] = data["trust"]
            save_state(STATE)
            self._json(STATE)

        elif path == "/remember":
            text = (data.get("text") or "").strip()[:500]
            if not text:
                self._json({"error": "empty"}, 400); return
            prov = str(data.get("provenance") or "stated").strip().lower()
            if prov not in memv2.PROVENANCE:
                self._json({"error": "provenance must be one of "
                            f"{list(memv2.PROVENANCE)}"}, 400)
                return
            remember(text, provenance=prov, source="remember")
            self._json({"ok": True, "reply": "Logged. I don't forget — feature, not a promise."})

        elif path == "/see":
            img = data.get("image") or ""
            mm = re.match(r"^data:(image/(?:png|jpeg|webp));base64,(.+)$", img, re.S)
            if not mm:
                self._json({"error": "bad image"}, 400); return
            q = (data.get("question") or
                 "This is the Commander's screen right now. Tell him what you see and give your "
                 "blunt take — what's good, what's off, what you'd fix first.")
            # screen analysis is conversational inference: ungated only while
            # paid models are disabled by default. When gated, the confirmation
            # binds image metadata (sha256/bytes/type) - never the multi-MB frame.
            if PAID_MODE:
                _see_canon = {"question": q,
                              "image_sha256": hashlib.sha256(img.encode()).hexdigest(),
                              "image_bytes": len(img),
                              "image_type": mm.group(1)}
                if not self._need_confirmation("chat.see", _see_canon, recipient="/see"):
                    return
            # persistent screen link: follow-ups carry chat history + a FRESH frame,
            # so "what about the title?" refers to what's on screen right now
            msgs = []
            for h in (data.get("history") or [])[-6:]:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    msgs.append({"role": h["role"], "content": str(h["content"])[:1500]})
            sysp = (persona(STATE, spoken=True) + mem_block() + jobs_block() + tools_block() +
                    " You are LOOKING AT THE COMMANDER'S LIVE SCREEN — the attached image is what it "
                    "shows at this exact moment (it may have changed since earlier questions). "
                    "Answer about what you actually see; be specific. When he asks for your "
                    "OPINION on something on screen, judge it per your honesty and humor "
                    "settings — what's weak, what you'd fix first, specifics over politeness. "
                    "A 'roast this' request deserves NAMED critiques: which section, which "
                    "words, what a first-time visitor actually sees and where their eye dies. "
                    "AFTER a critical take, if online research would sharpen the fix list "
                    "(how the best competitors do it, current best practices), OFFER it in "
                    "one dry sentence — e.g. 'Want me to put KIPP on studying how the top "
                    "communities do this, sir?' — and only ever PROPOSE with [DEPLOY: …] - the system asks him separately, so never imply the mission started. "
                    "acking with a NAMED squad member (CASE/KIPP/PLEX/N1X — the name you say "
                    "is who goes). "
                    "If he asks you to research, find, compare, audit, or otherwise DO WORK "
                    "about what's on screen (not just describe it), give a 1-2 sentence spoken "
                    "ack and END your reply with a new line containing exactly "
                    "[DEPLOY: <self-contained third-person brief that names what the screen "
                    "shows — the robot gets this exact screenshot attached automatically>].")
            msgs.append({"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": mm.group(1), "data": mm.group(2)}},
                {"type": "text", "text": q}]})
            try:
                reply = anthropic_chat(sysp, msgs, 400)
                deployed = None
                dep = re.search(r"\[DEPLOY:(.+?)\]\s*$", reply, re.S | re.I)
                if dep:
                    brief = re.sub(r"\s+", " ", dep.group(1)).strip()[:4000]
                    reply = reply[:dep.start()].strip()
                    if brief:
                        # propose only: a generated mission needs its own
                        # mission.exec confirmation before anything runs
                        nm = re.search(r"\b(CASE|KIPP|PLEX|N1X)\b", reply)
                        deployed = {"proposed": True, "brief": brief,
                                    "agent": nm.group(1) if nm else None}
                self._json({"reply": speakable(reply), "deployed": deployed})
            except Exception as e:
                self._json({"error": str(e)[:200]}, 500)

        elif path == "/act":
            aid = str(data.get("action_id") or "")
            act = ACTIONS.get(aid)
            if not act:
                self._json({"reply": "Nothing's queued under that id. Give me something "
                                     "to send first.", "refused": True}, 400); return
            # confirmation binds the EXACT immutable action object
            canonical = {"action_id": aid, "instruction": act["instruction"]}
            if not self._need_confirmation("act.exec", canonical, recipient="/act"):
                return
            if STATE.get("trust") != "confirm-to-act":
                self._json({"reply": "Trust is set to draft-safe. Flip it to CONFIRM-TO-ACT "
                                     "in the HUD if you want me actually pulling triggers.",
                            "refused": True}); return
            ACTIONS.pop(aid, None)               # single-use
            mid = start_mission(act["instruction"], agent="BARS", kind="ACT",
                                cost_bound=getattr(_COST_CAP, "value", 0) or 0)
            self._json({"reply": "Copy. Executing now — watch the board.",
                        "id": mid, "instruction": act["instruction"]})

        elif path == "/archive":
            one = (data.get("id") or "").strip()      # single-row ✕ → archive just it
            if one:
                m = MISSIONS.get(one)
                if not m or m["status"] == "EN ROUTE":
                    self._json({"error": "not archivable"}, 400); return
                done = [m]
            else:
                done = [m for m in MISSIONS.values() if m["status"] != "EN ROUTE"]
            try:
                ap = os.path.join(MISSIONS_DIR, "archive.json")
                arch = _load_json(ap) or []
                arch.extend(done)
                fd, tmp = tempfile.mkstemp(dir=MISSIONS_DIR)
                with os.fdopen(fd, "w") as f:
                    json.dump(arch, f, indent=1)
                os.replace(tmp, ap)
            except Exception:
                pass
            for m in done:
                MISSIONS.pop(m["id"], None)
            persist_missions()
            if one:
                self._json({"ok": True, "archived": 1})
            else:
                self._json({"ok": True, "archived": len(done),
                            "reply": f"Board cleared. {len(done)} jobs archived — "
                                     "reports stay on disk."})

        elif path == "/cancel_act":
            aid = str(data.get("action_id") or "")
            if aid:
                had = ACTIONS.pop(aid, None) is not None
            else:
                had = bool(ACTIONS); ACTIONS.clear()
            self._json({"reply": "Scrubbed." if had else "Nothing to cancel.", "ok": True})

        elif path == "/hue":
            ev = data.get("event", "")
            if ev in ("speak_start", "speak_end", "fail", "complete", "deploy"):
                hue.event(ev)
            # the same funnel animates the desktop BARS
            if ev == "speak_start":
                presence("state:speaking")
            elif ev in ("speak_end", "complete", "fail"):
                presence_idle_or_working()
            elif ev == "deploy":
                presence("state:working")
            self._json({"ok": True})

        elif path == "/takeover_speed":
            tier = (data.get("tier") or "").strip()
            if HANDS and tier in HANDS.SPEED_TIERS:
                if not self._need_confirmation("hands.config", {"tier": tier},
                                               recipient="/takeover_speed"):
                    return
                _receipt({"kind": "config", "lane": "hands.config", "paid": False,
                          "tier": tier})
                HANDS.set_speed(tier)
                try:                                  # persist to config.json
                    cfg = _load_json(os.path.join(ROOT, "config.json"))
                    cfg.setdefault("takeover", {})["speed"] = tier
                    with open(os.path.join(ROOT, "config.json"), "w") as f:
                        json.dump(cfg, f, indent=2)
                except Exception:
                    pass
                self._json({"ok": True, "tier": tier,
                            "model": HANDS.COMPUTER_MODEL})
            else:
                self._json({"error": "bad tier"}, 400)

        elif path == "/presence":
            cmd = data.get("cmd", "")
            if cmd == "show":
                _spawn_presence()
                time.sleep(0.35)         # let a fresh spawn bind its UDP port
                presence("show")
                presence_idle_or_working()
                self._json({"ok": True, "on": True})
            elif cmd == "hide":
                presence("hide")
                self._json({"ok": True, "on": False})
            else:
                self._json({"error": "bad cmd"}, 400)

        elif path == "/api/realtime_session":
            hold = self._paid_media_gate("realtime.exec", {}, "/api/realtime_session", 8000)
            if hold == "gated":
                return
            try:
                sess = mint_realtime()
                if hold: BUDGET.settle(hold, 8000)               # conservative: at estimate
                self._json(sess)
            except urllib.error.HTTPError as e:
                if hold: BUDGET.fail(hold)
                _receipt({"kind": "media_attempt", "lane": "realtime.exec", "paid": True,
                          "ok": False, "error": f"OpenAI {e.code}"})
                detail = ""
                try:
                    detail = e.read().decode()[:300]
                except Exception:
                    pass
                self._json({"error": f"OpenAI {e.code}: {detail or e.reason}"}, 502)
            except Exception as e:
                if hold: BUDGET.fail(hold)
                _receipt({"kind": "media_attempt", "lane": "realtime.exec", "paid": True,
                          "ok": False, "error": str(e)[:160]})
                self._json({"error": str(e)[:250]}, 500)

        elif path == "/voice":
            vid = (data.get("voice_id") or "").strip()
            name = (data.get("name") or "CUSTOM").strip()[:24]
            if not re.match(r"^[A-Za-z0-9]{12,40}$", vid):
                self._json({"error": "bad voice id"}, 400); return
            CONFIG["el_voice"] = vid
            CONFIG["el_voice_name"] = name
            try:  # persist so the pick survives restarts
                cfg = _load_json(CONFIG_PATH)
                cfg.setdefault("elevenlabs", {})["voice_id"] = vid
                cfg["elevenlabs"]["_voice_name"] = name
                fd, tmp = tempfile.mkstemp(dir=DATA)
                with os.fdopen(fd, "w") as f:
                    json.dump(cfg, f, indent=2)
                os.replace(tmp, CONFIG_PATH)
            except Exception:
                pass
            self._json({"ok": True, "voice": name})

        elif path == "/model":
            mid = (data.get("model") or "").strip()
            # Allow any OpenRouter slug OR catalog id so switcher stays live
            avail = provider_models()
            known = any(m["id"] == mid for m in MODELS) or (avail and mid in avail)
            if not mid or (not known and "/" not in mid and not mid.startswith("claude-")):
                self._json({"error": "unknown model"}, 400); return
            target_base = CONFIG.get("base_url") or ""
            if "/" in mid and not target_base.strip():
                target_base = "https://openrouter.ai/api/v1"
            _th = (_urlparse(target_base if "://" in target_base else "https://" + target_base)
                   .hostname or "").lower()
            _tb = _KEY_HOSTS.get(CONFIG["anthropic_key"])
            if _tb and _th and _th != _tb:
                self._json({"error": f"model switch refused: the configured key is bound "
                                     f"to {_tb}, not {_th}. Configure a key for {_th} first."},
                           400); return
            if not self._need_confirmation("model.switch", {"model": mid, "base_url": target_base},
                                           recipient="/model"):
                return
            _receipt({"kind": "config", "lane": "model.switch", "paid": False,
                      "model": mid, "base_url": target_base})
            CONFIG["model"] = mid
            CONFIG["base_url"] = target_base
            try:  # persist so the pick survives restarts
                cfg = _load_json(CONFIG_PATH)
                cfg.setdefault("model", {})["model"] = mid
                if "/" in mid:
                    cfg["model"]["base_url"] = CONFIG.get("base_url") or "https://openrouter.ai/api/v1"
                fd, tmp = tempfile.mkstemp(dir=DATA)
                with os.fdopen(fd, "w") as f:
                    json.dump(cfg, f, indent=2)
                os.replace(tmp, CONFIG_PATH)
            except Exception:
                pass
            label = next((m["label"] for m in MODELS if m["id"] == mid), mid)
            self._json({"ok": True, "model": mid, "label": label, "base_url": CONFIG.get("base_url") or ""})

        elif path == "/followup":
            mid = data.get("id", "")
            m = MISSIONS.get(mid)
            if not m or not m.get("follow_up"):
                # checked BEFORE consuming the single-use confirmation so a
                # dead follow-up never burns the user's approval
                self._json({"error": "no follow-up available"}, 400); return
            if not self._need_confirmation("mission.exec", data, recipient="/followup"):
                return
            # enforce the exact displayed bound for the follow-up, matching /act and /brief
            nid = start_mission(m["follow_up"],
                                cost_bound=getattr(_COST_CAP, "value", 0) or 0)
            self._json({"id": nid, "brief": m["follow_up"],
                        "agent": MISSIONS[nid]["agent"]})

        elif path == "/tts":
            text = (data.get("text") or "").strip()[:4000]     # input cap
            if not text:
                self._json({"error": "empty"}, 400); return
            hold = self._paid_media_gate("tts.exec", {"text": text}, "/tts",
                                         len(text) // 4 + 500)
            if hold == "gated":
                return
            try:
                audio, ctype = tts_bytes(text)
            except Exception as e:
                if hold: BUDGET.fail(hold)
                _receipt({"kind": "media_attempt", "lane": "tts.exec", "paid": True,
                          "ok": False, "error": str(e)[:160]})
                self._json({"error": str(e)[:200], "fallback": True, "browser_fallback": True}, 200); return
            if hold: BUDGET.settle(hold, len(text) // 4 + 500)   # conservative: at estimate
            if not audio:
                if hold: BUDGET.fail(hold)       # paid lane unavailable: conservative settle
                _receipt({"kind": "media_attempt", "lane": "tts.exec", "paid": True,
                          "ok": False, "error": "provider unavailable, browser fallback"})
                self._json({"fallback": True, "browser_fallback": True, "text": text}, 200); return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)

        else:
            self._json({"error": "not found"}, 404)

# ---------------------------------------------------------------- duplex brain
# OpenAI-compatible endpoint for ElevenLabs Agents (full-duplex voice).
# Separate port + bearer token so a tunnel NEVER exposes the full assistant
# (same rule as Jarvis: funnel only the one token-gated route). See DUPLEX.md.

class DuplexHandler(BaseHTTPRequestHandler):
    server_version = "BARS-duplex/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[duplex] %s\n" % (fmt % args))

    def _deny(self, code=401):
        body = json.dumps({"error": "unauthorized"}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            body = b'{"ok": true, "who": "BARS duplex brain"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._deny(404)

    DUPLEX_MAX_BODY = 1_000_000
    DUPLEX_RL = {}
    DUPLEX_RL_LOCK = threading.Lock()

    def _duplex_rate_ok(self):
        ip = self.client_address[0] if self.client_address else "?"
        now = time.time()
        with self.DUPLEX_RL_LOCK:
            calls = [t for t in self.DUPLEX_RL.get(ip, []) if now - t < 60]
            if len(calls) >= 30:
                self.DUPLEX_RL[ip] = calls
                return False
            calls.append(now)
            self.DUPLEX_RL[ip] = calls
            return True

    def do_POST(self):
        if self.path.split("?")[0] != "/v1/chat/completions":
            self._deny(404); return
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {DUPLEX_TOKEN}"):
            self._deny(); return
        if not self._duplex_rate_ok():
            self._deny(429); return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > self.DUPLEX_MAX_BODY:
                self._deny(413); return
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("body must be a JSON object")
                _msgs = data.get("messages")
                if _msgs is not None and not (
                        isinstance(_msgs, list)
                        and all(isinstance(m, dict) and "role" in m for m in _msgs)):
                    raise ValueError("messages must be a list of role/content objects")
            except Exception:
                self._deny(400); return
            msgs = []
            for msg in (data.get("messages") or [])[-12:]:
                role = msg.get("role")
                c = msg.get("content")
                if isinstance(c, list):
                    c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
                if role in ("user", "assistant") and c:
                    msgs.append({"role": role, "content": str(c)[:2000]})
            if not msgs or msgs[-1]["role"] != "user":
                msgs.append({"role": "user", "content": "(silence)"})
            reply = anthropic_chat(persona(STATE, spoken=True) + mem_block(), msgs,
                                   max_tokens=300).strip()
        except Exception as e:
            reply = f"Brain glitch: {str(e)[:80]}"
        rid = "chatcmpl-" + uuid.uuid4().hex[:16]
        if data.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for delta in ({"role": "assistant"}, {"content": reply}):
                chunk = {"id": rid, "object": "chat.completion.chunk",
                         "model": "bars", "choices": [{"index": 0, "delta": delta,
                                                       "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            end = {"id": rid, "object": "chat.completion.chunk", "model": "bars",
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(end)}\n\ndata: [DONE]\n\n".encode())
        else:
            body = json.dumps({"id": rid, "object": "chat.completion", "model": "bars",
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant",
                                                        "content": reply}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

# ---------------------------------------------------------------- main

def main():
    for d in (MISSIONS_DIR, WORKBENCH, BUILDS_DIR):
        os.makedirs(d, exist_ok=True)
    load_missions()
    try:
        stale = BUDGET.sweep_stale()
        if stale:
            print(f"[bars] swept {len(stale)} stale budget holds at startup")
    except Exception as e:
        print(f"[bars] budget state error at startup: {e}")
    _locks = os.path.join(MISSIONS_DIR, "locks")
    if os.path.isdir(_locks):
        for _lf in os.listdir(_locks):
            _mid = _lf[:-5] if _lf.endswith(".lock") else ""
            if _mid and MISSIONS.get(_mid, {}).get("status") != "EN ROUTE":
                try:
                    os.unlink(os.path.join(_locks, _lf))   # stale: no live runner
                except OSError:
                    pass
    for _mid in _RESUME:                      # restart recovery (opt-in)
        if _mid in MISSIONS:
            MISSIONS[_mid]["status"] = "EN ROUTE"
            threading.Thread(target=run_mission, args=(_mid,), daemon=True).start()
    init_hands()
    duplex = ThreadingHTTPServer(("127.0.0.1", DUPLEX_PORT), DuplexHandler)
    threading.Thread(target=duplex.serve_forever, daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)

    def _term(_signum, _frame):
        try:
            save_state(STATE)
            persist_missions()
        except Exception:
            pass
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _term)
    print(f"BARS online. The culture is live. → http://{BIND}:{PORT}   "
          f"(brain: {'OK' if CONFIG['anthropic_key'] else 'MISSING'} · "
          f"voice: {'OK' if CONFIG['el_key'] and CONFIG['el_voice'] else 'groq/browser fallback'} · "
          f"claude CLI: {'OK' if find_claude() else 'internal worker' if INTERNAL_WORKER else 'MISSING'} · "
          f"hue: {hue.status()['state']} · duplex brain: 127.0.0.1:{DUPLEX_PORT} · "
          f"auth: {'token' if OPERATOR_TOKEN else 'open local mode'} · data: {DATA})")
    if not os.environ.get("BARS_NO_BROWSER") and BIND in ("127.0.0.1", "localhost"):
        # Auto-open browser (local runs only)
        try:
            import webbrowser as _wb2
            threading.Thread(target=lambda: (time.sleep(1.5), _wb2.open(f"http://localhost:{PORT}")), daemon=True).start()
        except Exception:
            pass
    srv.serve_forever()

if __name__ == "__main__":
    main()
