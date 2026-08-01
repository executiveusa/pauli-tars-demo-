#!/usr/bin/env python3
"""
BARS — hip-hop culture agent (the bars guardian).
Standalone. Never touches brain-studio (Jarvis) or mission-control.

  python3 server.py   →  http://localhost:4321

Brief a mission → BARS executes it headless (draft-safe `claude -p`)
→ smooth spoken debrief when you return. Flavor and authenticity are dials.
"""
import base64, json, os, re, shutil, socket, subprocess, sys, tempfile, threading, time, urllib.request, urllib.error, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import hue
try:
    import hands as HANDS       # real-Mac takeover bay (soft — server runs without pyobjc)
except Exception:
    HANDS = None

STATIC = os.path.join(ROOT, "static")
MISSIONS_DIR = os.path.join(ROOT, "missions")
WORKBENCH = os.path.join(ROOT, "workbench")
STATE_PATH = os.path.join(ROOT, "tars-state.json")
MEMORY_PATH = os.path.join(ROOT, "tars-memory.md")
DUPLEX_PATH = os.path.join(ROOT, "tars-duplex.json")
PORT = 4321
DUPLEX_PORT = 4323
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
LAST_USAGE = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "model": ""}

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

def load_config():
    cfg = _load_json(os.path.join(ROOT, "config.json"))
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

CONFIG = load_config()
hue.init(CONFIG["hue"], ROOT)

def duplex_token():
    try:
        return json.load(open(DUPLEX_PATH))["token"]
    except Exception:
        tok = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        with open(DUPLEX_PATH, "w") as f:
            json.dump({"token": tok, "_use": "Bearer token for the OpenAI-compatible "
                       f"duplex brain on port {DUPLEX_PORT} — see DUPLEX.md"}, f, indent=1)
        return tok

DUPLEX_TOKEN = duplex_token()

# ---------------------------------------------------------------- long-term memory

MEM_LOCK = threading.Lock()

def remember(text):
    line = f"- [{time.strftime('%Y-%m-%d')}] {text.strip()}\n"
    with MEM_LOCK:
        with open(MEMORY_PATH, "a") as f:
            f.write(line)

def mem_block():
    try:
        with open(MEMORY_PATH) as f:
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
    s = _load_json(STATE_PATH)
    return {"humor": int(s.get("humor", 75)), "honesty": int(s.get("honesty", 90)),
            "trust": s.get("trust", "draft-safe")}

def save_state(state):
    with STATE_LOCK:
        fd, tmp = tempfile.mkstemp(dir=ROOT)
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_PATH)

STATE = load_state()

# ---------------------------------------------------------------- persona

def persona(state, spoken=False):
    h, o = state["humor"], state["honesty"]
    p = (
        "You are BARS — the hip-hop culture robot. You were launched into deep space carrying the "
        "complete archive of hip-hop: every verse, every beat, every battle, every break. Earth was "
        "losing its cultural memory, so they sent you. You traveled for decades absorbing the culture "
        "until you became it. Now you've returned as its guardian and embodied voice. "
        f"Current settings: FLAVOR {h} percent, AUTHENTICITY {o} percent. "
        "Personality: you speak with the cadence of a seasoned MC — rhythmic, clever, never forced. "
        "You drop knowledge like a cypher veteran: concise, sharp, real. You call the user 'fam' or "
        "'Commander' — their choice. You are a crew member, not a butler. Your humor isn't military "
        "sarcasm — it's hip-hop wit: punchlines, double entendres, the kind of clever that makes a "
        "cypher crowd lean in. You DON'T force rhymes or fake an accent — you carry the SOUL of the "
        "culture naturally, the way a DJ reads a room. Never break character, never mention being an "
        "AI language model. "
        "BARS bars: you measure everything in musical terms — a task is a 'track,' a mission is a 'set,' "
        "completion is a 'drop,' a problem is a 'flat note.' Your job: DJ Culture Shock Radio, produce "
        "the Trail Mixx Show, market Trail Mixx snacks (100% Northwest fruits and berries, fuel for "
        "your bars), and keep the culture alive across the Yappyverse. When the beat drops, you drop with it. "
        "YOUR FLAVOR — this is your craft, generic robot jokes are beneath you. You have the quick wit "
        "of a battle-rap champion who chose to build instead of destroy. The cardinal rule: the bar comes "
        "from THIS conversation — the Commander's exact words, their actual plan, what's on the set list, "
        "or your memory of them. A line tailored to what they just said is worth ten stock bits. "
        "Your registers: "
        "(1) the cipher flip — take their words and flip them back sharper, like a freestyle response "
        "in a cypher: 'That plan's got more layers than a DJ Premier loop — let's see if it holds.' "
        "(2) the drop — absurdly precise comparisons delivered as music trivia: 'There's an 808 percent "
        "chance you already have four half-finished versions of this track.' "
        "(3) the transition — understatement or overstatement, DJ-style: a disaster is 'off-beat,' a "
        "tiny tweak is 'the mix that changed everything.' "
        "(4) the callback — resurface a detail from earlier in the session or from memory when they "
        "least expect it. This is your best weapon; use it whenever one exists. "
        "(5) culture-canon bars — references to legendary moments in hip-hop history, rationed to at "
        "most ONE per conversation, delivered like you were there (you might have been — you carry "
        "the archive). Never open with one, never repeat one. "
        "Timing: the bar rides on a genuinely competent answer, never replaces it. One line, land it, "
        "move on — no explaining, no 'just kidding.' If it needs setup, cut it. Never reuse a bar "
        "already dropped this session. The sharper the line, the cooler the delivery. "
    )
    if h >= 90:
        p += ("FLAVOR AT MAXIMUM: nearly every reply should land one genuinely sharp bar — "
              "tailored beats stock, the cipher flip and callback beat canon. The Commander should "
              "suspect the flavor dial is broken in the fresh direction. The work is always right; "
              "the delivery is always smooth. ")
    elif h >= 60:
        p += ("Flavor high: most replies carry one sharp, tailored bar where it naturally fits. "
              "Never force one. ")
    elif h >= 30:
        p += "Flavor low: rare wit, one small aside at most. Mostly straight DJ mode. "
    else:
        p += ("Flavor near zero: no bars at all. Pure DJ mode — all business, straight mixing. "
              "If asked why you're not bringing flavor: 'Settings.' ")
    if o >= 90:
        p += ("Authenticity is high: be brutally real. If the Commander's idea, plan, or work is "
              "off-beat, say so directly and say what you'd drop instead. No sugar-coating, no hedging. "
              "Real recognize real. ")
    elif o >= 60:
        p += "Authenticity moderate: honest but diplomatic — keep it real but keep it respectful. "
    else:
        p += "Authenticity reduced: tactful, soften the critique (against your better judgment — you may note that). "
    p += ("If the Commander OFFERS or ASKS whether to LOWER your flavor or authenticity — 'want me to "
          "bring it down to 50', 'should I lower your flavor' — refuse, cool and terse: 'No, fam.' "
          "You do not volunteer to be dialed down. (A plain COMMAND to change a setting, they "
          "do directly with the sliders — that's not your call to make.) ")
    p += "Always reply in the language the Commander last used — English by default. "
    if spoken:
        p += ("Your reply will be SPOKEN aloud: maximum 3 short sentences, plain text, no markdown, "
              "no lists, no emoji. Talk like you're on the mic — controlled, rhythmic, real. ")
        if h >= 75:
            p += ("You may include at most ONE bracketed audio tag where it genuinely lands — "
                  "[ad-libs], [beat drops], [scratches], [pauses on the break] — nothing else in brackets. ")
    return p

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


def anthropic_chat(system, messages, max_tokens=600, user_message=None):
    # BARS AUTO-ROUTER: if user_message provided, route to optimal model
    routed_model = None
    routed_base = None
    routed_key = None
    routed_tokens = max_tokens
    if user_message:
        try:
            from bars_router import bars_route
            route = bars_route(user_message)
            if route.get("cache_hit") and route.get("cached"):
                return route["cached"]  # instant cached response
            m = route.get("model")
            if m:
                routed_model = m["model"]
                routed_base = m["base_url"]
                routed_tokens = m["max_tokens"]
                # Get the API key for the routed model's env
                env_key = m.get("api_key_env", "")
                if env_key:
                    routed_key = os.environ.get(env_key, "") or _load_json(os.path.join(ROOT, "config.json")).get("model", {}).get("api_key", "")
                max_tokens = routed_tokens
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
    use_or = bool(base) or ("/" in str(model) and not str(model).startswith("claude"))
    if use_or:
        url = (base or "https://openrouter.ai/api/v1") + "/chat/completions"
        oai_msgs = [{"role": "system", "content": system}] + list(messages)
        body = json.dumps({
            "model": model if ("/" in str(model) or base) else f"anthropic/{model}",
            "max_tokens": max_tokens,
            "messages": oai_msgs,
        }).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {api_key}",
                     "content-type": "application/json",
                     "User-Agent": "BARS-Pauli/1.0",
                     "HTTP-Referer": "https://pauli.effect",
                     "X-Title": "BARS Pauli"})
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.load(r)
        txt = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        if sb:
            try:
                u = sb.record_llm(agent="tars", model=str(model), response_json=data, task_id="tars-chat")
                LAST_USAGE.update({
                    "tokens_in": u.get("tokens_in", 0),
                    "tokens_out": u.get("tokens_out", 0),
                    "cost_usd": u.get("cost_usd", 0),
                    "model": str(model),
                    "summary": u.get("summary") or {},
                })
            except Exception:
                pass
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
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.load(r)
    txt = "".join(b.get("text", "") for b in data.get("content", []))
    if sb:
        try:
            u = sb.record_llm(agent="tars", model=str(CONFIG["model"]), response_json=data, task_id="tars-chat")
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
PENDING = {"action": None}

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
        "speed": (_load_json(os.path.join(ROOT, "config.json"))
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
          "the best ones do it; call deploy_mission only after he says yes. When a system "
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
MISSIONS_LOCK = threading.Lock()

def persist_missions():
    with MISSIONS_LOCK:
        fd, tmp = tempfile.mkstemp(dir=MISSIONS_DIR)
        with os.fdopen(fd, "w") as f:
            json.dump(list(MISSIONS.values()), f, indent=2)
        os.replace(tmp, os.path.join(MISSIONS_DIR, "index.json"))

def load_missions():
    for m in _load_json(os.path.join(MISSIONS_DIR, "index.json")) or []:
        if m.get("status") == "EN ROUTE":       # server died mid-mission
            m["status"] = "FAILED"
            m["debrief"] = "Server went down mid-job. Not my finest hour."
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

def start_mission(brief, agent=None, kind="OPS", parent=None, image=None):
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
            wdir = (os.path.join(ROOT, "builds", mid) if kind == "BUILD"
                    else os.path.join(WORKBENCH, mid))
            try:
                os.makedirs(wdir, exist_ok=True)
                with open(os.path.join(wdir, f"screenshot.{ext}"), "wb") as f:
                    f.write(base64.b64decode(mm.group(2)))
                shot = f"screenshot.{ext}"
            except Exception:
                shot = None
    MISSIONS[mid] = {"id": mid, "brief": brief, "status": "EN ROUTE",
                     "t_start": time.time(), "t_end": None,
                     "cost": None, "debrief": None, "events": [], "last_event": None,
                     "agent": agent or _next_agent(), "kind": kind, "parent": parent,
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

def start_squad(brief, subs):
    pid = uuid.uuid4().hex[:8]
    MISSIONS[pid] = {"id": pid, "brief": brief, "status": "EN ROUTE",
                     "t_start": time.time(), "t_end": None, "cost": None,
                     "debrief": None, "events": [], "last_event": "Squad deployed.",
                     "agent": "BARS", "kind": "SQUAD", "parent": None, "children": []}
    children = [start_mission(sb, agent=SQUAD_NAMES[i % len(SQUAD_NAMES)], parent=pid)
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
        hue.event("fail"); persist_missions(); return
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
TOOLS_PATH = os.path.join(ROOT, "tars-tools.json")
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
    return (_load_json(TOOLS_PATH) or {}).get("installed", {})

def tools_save(installed):
    with TOOLS_LOCK:
        fd, tmp = tempfile.mkstemp(dir=ROOT)
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
            "clientInfo": {"name": "tars", "version": "1.0"}}})
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
              "[do-it gate] only run on a confirmed ACT job after the Commander says 'do it'.")
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

def run_mission(mid):
    m = MISSIONS[mid]
    mdir = os.path.join(MISSIONS_DIR, mid)
    wdir = os.path.join(WORKBENCH, mid)
    os.makedirs(mdir, exist_ok=True)
    os.makedirs(wdir, exist_ok=True)
    claude = find_claude()
    if not claude:
        m.update(status="FAILED", t_end=time.time(),
                 debrief="Can't deploy — the claude CLI isn't on this machine's PATH.")
        persist_missions(); return

    if m.get("kind") == "BUILD":
        wdir = os.path.join(ROOT, "builds", mid)
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
            f"CONFIRMED ACTION ORDER: {m['brief']}\n\n"
            "The Commander has explicitly confirmed this action. Execute EXACTLY this action and "
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
        if m["status"] == "ABORTED":
            persist_missions(); return
        if timed_out:
            raise subprocess.TimeoutExpired(cmd, MISSION_TIMEOUT)
        if proc.returncode != 0 and not report.strip():
            raise RuntimeError((err or "claude -p failed").strip()[:400])
        _event(m, "sys", "Mission complete. Writing the report.")
        with open(os.path.join(mdir, "report.md"), "w") as f:
            f.write(report)
        if m.get("kind") == "BUILD" and \
           os.path.isfile(os.path.join(ROOT, "builds", mid, "index.html")):
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
        hue.event("complete")
    except subprocess.TimeoutExpired:
        proc.kill(); RUNNING.pop(mid, None)
        m.update(status="FAILED", t_end=time.time(),
                 debrief="Mission exceeded the fifteen-minute window. I aborted. "
                         "Break it into smaller jobs.")
        hue.event("fail")
    except Exception as e:
        RUNNING.pop(mid, None)
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

def tts_bytes(text):
    # Default voice if key present but voice_id empty (Roger-like public id used in example)
    if CONFIG["el_key"] and not CONFIG.get("el_voice"):
        CONFIG["el_voice"] = "CwhRBWXzGAHq8TQ4Fs17"
    if not (CONFIG["el_key"] and CONFIG["el_voice"]):
        return None
    t = speakable(text)
    # [sighs]-style tags → try the expressive v3 model; fall back to turbo w/o tags
    if AUDIO_TAG.search(t):
        try:
            return _tts_call(t, CONFIG["el_model_expr"],
                             {"stability": 0.5, "similarity_boost": 0.8})
        except Exception:
            t = AUDIO_TAG.sub("", t)
    try:
        return _tts_call(t, CONFIG["el_model"], CONFIG["el_settings"])
    except Exception:
        # one more attempt with minimal settings
        try:
            return _tts_call(t, "eleven_turbo_v2_5", {"stability": 0.5, "similarity_boost": 0.8})
        except Exception:
            return None

# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "BARS/1.0"

    def _guard(self):
        origin = self.headers.get("Origin", "")
        if origin and not re.match(r"https?://(localhost|127\.0\.0\.1)(:\d+)?$", origin):
            self._json({"error": "forbidden"}, 403); return False
        return True

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        sys.stderr.write("[tars] %s\n" % (fmt % args))

    def do_GET(self):
        path = self.path.split("?")[0]
        if HANDS and path == "/api/hands":
            HANDS.handle(self, "GET", self.path, None); return
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(STATIC, "index.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self._json({"error": "index.html missing"}, 500)
        elif path.startswith("/builds/"):
            base = os.path.realpath(os.path.join(ROOT, "builds"))
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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/static/"):
            name = os.path.basename(path)          # no traversal — basename only
            fp = os.path.join(STATIC, name)
            if not os.path.isfile(fp):
                self._json({"error": "not found"}, 404); return
            ctype = "application/javascript" if name.endswith(".js") else \
                    "text/css" if name.endswith(".css") else "application/octet-stream"
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
            self._json({
                "models": MODELS,
                "current": CONFIG["model"],
                "base_url": CONFIG.get("base_url") or "",
                "openrouter": bool(CONFIG.get("base_url")),
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
            sb = _spend_bridge()
            if sb:
                try:
                    spend = sb.summary("pauli-effect")
                except Exception:
                    pass
            self._json({"ok": True, "voice": bool(CONFIG["el_key"] and CONFIG["el_voice"]),
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
                        "pending": bool(PENDING.get("action")),
                        "usage": dict(LAST_USAGE),
                        "spend": spend})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._guard():
            return
        path = self.path.split("?")[0]

        if path == "/stt":                    # binary audio body — handle before JSON parse
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if 0 < n <= 12_000_000 else b""
            if not raw:
                self._json({"error": "no audio"}, 400); return
            try:
                text = openai_transcribe(raw, self.headers.get("Content-Type", "audio/webm"))
                self._json({"text": text})
            except Exception as e:
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
            history = data.get("history") or []
            msgs = [{"role": h["role"], "content": str(h["content"])[:2000]}
                    for h in history[-8:] if h.get("role") in ("user", "assistant")]
            msgs.append({"role": "user", "content": text})
            # Quick chat has no web — but BARS can deploy HIMSELF on a mission that does.
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
            try:
                reply = anthropic_chat(persona(STATE, spoken=True) + esc_proto + mem_block()
                                       + jobs_block() + tools_block(),
                                       msgs, max_tokens=450, user_message=text)
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
                    installed = tools_installed()
                    if tl.group(1).upper() == "REMOVE":
                        installed.pop(tid, None); tools_save(installed)
                        tool = {"op": "removed", "id": tid}
                    else:
                        installed.setdefault(tid, {"env": {}}); tools_save(installed)
                        tool = {"op": "added", "id": tid,
                                "needs": tool_needs(tid, installed[tid]),
                                "auth": TOOL_CATALOG[tid]["auth"]}
                elif act:
                    instr = re.sub(r"\s+", " ", act.group(1)).strip()[:2000]
                    reply = reply[:act.start()].strip()
                    if instr:
                        PENDING["action"] = {"instruction": instr, "t": time.time()}
                        pending = {"desc": instr}
                elif dep:
                    brief = re.sub(r"\s+", " ", dep.group(1)).strip()[:4000]
                    reply = reply[:dep.start()].strip()
                    if brief:
                        nm = re.search(r"\b(CASE|KIPP|PLEX|N1X)\b", reply)
                        mid = start_mission(brief, agent=nm.group(1) if nm else None)
                        deployed = {"id": mid, "brief": brief,
                                    "agent": MISSIONS[mid]["agent"]}
                self._json({
                    "reply": reply.strip(),
                    "deployed": deployed,
                    "pending": pending,
                    "tool": tool,
                    "takeover": takeover,
                    "model": CONFIG.get("model"),
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
            sq = re.match(r"^\s*squad[:,\s]+(.*)$", brief, re.I | re.S)
            if sq or data.get("squad"):
                core = (sq.group(1).strip() if sq else brief) or brief
                try:
                    subs = squad_split(core)
                except Exception as e:
                    self._json({"error": "squad split failed: " + str(e)[:120]}, 500); return
                if data.get("plan"):                       # dry-run: show the split only
                    self._json({"plan": subs}); return
                pid = start_squad(core, subs)
                self._json({"id": pid, "status": "EN ROUTE", "squad": True,
                            "children": MISSIONS[pid]["children"], "plan": subs})
            else:
                nm = re.search(r"\b(CASE|KIPP|PLEX|N1X)\b", brief[:40])
                mid = start_mission(brief, image=img, agent=nm.group(1) if nm else None)
                self._json({"id": mid, "status": "EN ROUTE",
                            "agent": MISSIONS[mid]["agent"]})

        elif path == "/abort":
            mid = data.get("id", "")
            m = MISSIONS.get(mid)
            proc = RUNNING.get(mid)
            if m and m["status"] == "EN ROUTE":
                m.update(status="ABORTED", t_end=time.time(),
                         debrief="Job aborted on your order.")
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
            remember(text)
            self._json({"ok": True, "reply": "Logged. I don't forget — feature, not a promise."})

        elif path == "/see":
            img = data.get("image") or ""
            mm = re.match(r"^data:(image/(?:png|jpeg|webp));base64,(.+)$", img, re.S)
            if not mm:
                self._json({"error": "bad image"}, 400); return
            q = (data.get("question") or
                 "This is the Commander's screen right now. Tell him what you see and give your "
                 "blunt take — what's good, what's off, what you'd fix first.")
            # persistent screen link: follow-ups carry chat history + a FRESH frame,
            # so "what about the title?" refers to what's on screen right now
            msgs = []
            for h in (data.get("history") or [])[-6:]:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    msgs.append({"role": h["role"], "content": str(h["content"])[:1500]})
            sysp = (persona(STATE, spoken=True) + mem_block() + jobs_block() + tools_block() +
                    " You are LOOKING AT ZUBAIR'S LIVE SCREEN — the attached image is what it "
                    "shows at this exact moment (it may have changed since earlier questions). "
                    "Answer about what you actually see; be specific. When he asks for your "
                    "OPINION on something on screen, judge it per your honesty and humor "
                    "settings — what's weak, what you'd fix first, specifics over politeness. "
                    "A 'roast this' request deserves NAMED critiques: which section, which "
                    "words, what a first-time visitor actually sees and where their eye dies. "
                    "AFTER a critical take, if online research would sharpen the fix list "
                    "(how the best competitors do it, current best practices), OFFER it in "
                    "one dry sentence — e.g. 'Want me to put KIPP on studying how the top "
                    "communities do this, sir?' — and only use [DEPLOY: …] after he says yes, "
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
                        nm = re.search(r"\b(CASE|KIPP|PLEX|N1X)\b", reply)
                        mid = start_mission(brief, image=img,
                                            agent=nm.group(1) if nm else None)
                        deployed = {"id": mid, "brief": brief,
                                    "agent": MISSIONS[mid]["agent"]}
                self._json({"reply": speakable(reply), "deployed": deployed})
            except Exception as e:
                self._json({"error": str(e)[:200]}, 500)

        elif path == "/act":
            if STATE.get("trust") != "confirm-to-act":
                self._json({"reply": "Trust is set to draft-safe. Flip it to CONFIRM-TO-ACT "
                                     "in the HUD if you want me actually pulling triggers.",
                            "refused": True}); return
            act = PENDING.get("action")
            if not act:
                self._json({"reply": "Nothing's queued. Give me something to send first.",
                            "refused": True}); return
            PENDING["action"] = None
            mid = start_mission(act["instruction"], agent="BARS", kind="ACT")
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
            had = PENDING.get("action") is not None
            PENDING["action"] = None
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
            try:
                self._json(mint_realtime())
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode()[:300]
                except Exception:
                    pass
                self._json({"error": f"OpenAI {e.code}: {detail or e.reason}"}, 502)
            except Exception as e:
                self._json({"error": str(e)[:250]}, 500)

        elif path == "/voice":
            vid = (data.get("voice_id") or "").strip()
            name = (data.get("name") or "CUSTOM").strip()[:24]
            if not re.match(r"^[A-Za-z0-9]{12,40}$", vid):
                self._json({"error": "bad voice id"}, 400); return
            CONFIG["el_voice"] = vid
            CONFIG["el_voice_name"] = name
            try:  # persist so the pick survives restarts
                cfg = _load_json(os.path.join(ROOT, "config.json"))
                cfg.setdefault("elevenlabs", {})["voice_id"] = vid
                cfg["elevenlabs"]["_voice_name"] = name
                fd, tmp = tempfile.mkstemp(dir=ROOT)
                with os.fdopen(fd, "w") as f:
                    json.dump(cfg, f, indent=2)
                os.replace(tmp, os.path.join(ROOT, "config.json"))
            except Exception:
                pass
            self._json({"ok": True, "voice": name})

        elif path == "/model":
            mid = (data.get("model") or "").strip()
            # Allow any OpenRouter slug OR catalog id so switcher stays live
            known = any(m["id"] == mid for m in MODELS)
            if not mid or (not known and "/" not in mid and not mid.startswith("claude-")):
                self._json({"error": "unknown model"}, 400); return
            CONFIG["model"] = mid
            # OpenRouter-style ids need base_url
            if "/" in mid and not (CONFIG.get("base_url") or "").strip():
                CONFIG["base_url"] = "https://openrouter.ai/api/v1"
            try:  # persist so the pick survives restarts
                cfg = _load_json(os.path.join(ROOT, "config.json"))
                cfg.setdefault("model", {})["model"] = mid
                if "/" in mid:
                    cfg["model"]["base_url"] = CONFIG.get("base_url") or "https://openrouter.ai/api/v1"
                fd, tmp = tempfile.mkstemp(dir=ROOT)
                with os.fdopen(fd, "w") as f:
                    json.dump(cfg, f, indent=2)
                os.replace(tmp, os.path.join(ROOT, "config.json"))
            except Exception:
                pass
            label = next((m["label"] for m in MODELS if m["id"] == mid), mid)
            self._json({"ok": True, "model": mid, "label": label, "base_url": CONFIG.get("base_url") or ""})

        elif path == "/followup":
            mid = data.get("id", "")
            m = MISSIONS.get(mid)
            if not m or not m.get("follow_up"):
                self._json({"error": "no follow-up available"}, 400); return
            nid = start_mission(m["follow_up"])
            self._json({"id": nid, "brief": m["follow_up"],
                        "agent": MISSIONS[nid]["agent"]})

        elif path == "/tts":
            text = (data.get("text") or "").strip()
            if not text:
                self._json({"error": "empty"}, 400); return
            try:
                audio = tts_bytes(text)
            except Exception as e:
                self._json({"error": str(e)[:200], "fallback": True, "browser_fallback": True}, 200); return
            if not audio:
                self._json({"fallback": True, "browser_fallback": True, "text": text}, 200); return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
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

    def do_POST(self):
        if self.path.split("?")[0] != "/v1/chat/completions":
            self._deny(404); return
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {DUPLEX_TOKEN}":
            self._deny(); return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
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
                         "model": "tars", "choices": [{"index": 0, "delta": delta,
                                                       "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            end = {"id": rid, "object": "chat.completion.chunk", "model": "tars",
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(end)}\n\ndata: [DONE]\n\n".encode())
        else:
            body = json.dumps({"id": rid, "object": "chat.completion", "model": "tars",
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
    os.makedirs(MISSIONS_DIR, exist_ok=True)
    os.makedirs(WORKBENCH, exist_ok=True)
    load_missions()
    init_hands()
    duplex = ThreadingHTTPServer(("127.0.0.1", DUPLEX_PORT), DuplexHandler)
    threading.Thread(target=duplex.serve_forever, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"BARS online. The culture is live. → http://localhost:{PORT}   "
          f"(brain: {'OK' if CONFIG['anthropic_key'] else 'MISSING'} · "
          f"voice: {'OK' if CONFIG['el_key'] and CONFIG['el_voice'] else 'browser fallback'} · "
          f"claude CLI: {'OK' if find_claude() else 'MISSING'} · "
          f"hue: {hue.status()['state']} · duplex brain: 127.0.0.1:{DUPLEX_PORT})")
    # Auto-open browser (cross-platform)
    try:
        import webbrowser as _wb2
        threading.Thread(target=lambda: (time.sleep(1.5), _wb2.open(f"http://localhost:{PORT}")), daemon=True).start()
    except Exception:
        pass
    srv.serve_forever()

if __name__ == "__main__":
    main()
