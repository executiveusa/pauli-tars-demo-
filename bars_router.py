"""BARS Router V2 — deterministic fast lanes + lazy tools + safe escalation.

Design goals:
- zero-model responses for trivial deterministic acknowledgements
- fast default model for most conversational/tool-routing work
- stronger worker/reasoner lanes only when task complexity/risk justifies them
- Vercel AI Gateway when credentials are present, with provider-specific fallbacks
- no provider key is ever reused against the wrong endpoint
- lazy tool activation keeps prompt/tool context small
"""

import os
import re

GATEWAY_BASE = "https://ai-gateway.vercel.sh/v1"

# Canonical lanes. `fallbacks` are model fallbacks for the gateway layer to use
# when the caller supports them; server.py currently consumes the primary model.
LANES = {
    "flash": {
        "model": "google/gemini-3.5-flash-lite",
        "fallbacks": ["google/gemini-3.6-flash", "openai/gpt-5.4-nano"],
        "max_tokens": 320,
        "strength": "fast_default",
    },
    "worker": {
        "model": "google/gemini-3.6-flash",
        "fallbacks": ["openai/gpt-5.6-sol", "anthropic/claude-sonnet-5"],
        "max_tokens": 700,
        "strength": "code_and_tools",
    },
    "reasoner": {
        "model": "openai/gpt-5.6-sol",
        "fallbacks": ["anthropic/claude-sonnet-5", "google/gemini-3.6-flash"],
        "max_tokens": 1100,
        "strength": "deep_reasoning",
    },
    "judge": {
        "model": "anthropic/claude-opus-5",
        "fallbacks": ["openai/gpt-5.6-sol", "anthropic/claude-sonnet-5"],
        "max_tokens": 1400,
        "strength": "independent_review",
    },
}

# Provider-native fallbacks only used when AI Gateway credentials are absent.
# These retain the existing runtime's compatibility without pretending they are free.
NATIVE_FALLBACKS = {
    "flash": [
        ("llama-3.1-8b-instant", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        ("deepseek/deepseek-chat-v3.1", "https://openrouter.ai/api/v1", "OPEN_ROUTER_API"),
    ],
    "worker": [
        ("groq/qwen3-32b", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        ("deepseek/deepseek-chat-v3.1", "https://openrouter.ai/api/v1", "OPEN_ROUTER_API"),
    ],
    "reasoner": [
        ("deepseek/deepseek-chat-v3.1", "https://openrouter.ai/api/v1", "OPEN_ROUTER_API"),
    ],
    "judge": [
        ("openrouter/nousresearch/hermes-3-llama-3.1-405b:free", "https://openrouter.ai/api/v1", "OPEN_ROUTER_API"),
    ],
}

DIRECT_RESPONSES = {
    "ok": "Locked.",
    "okay": "Locked.",
    "got it": "Locked.",
    "thanks": "Anytime.",
    "thank you": "Anytime.",
    "cool": "Locked.",
}

HIGH_RISK = (
    "security", "production", "incident", "breach", "rollback", "migration",
    "architecture decision", "delete", "payment", "billing", "credentials",
)
JUDGE_TRIGGERS = (
    "final review", "independent review", "approve release", "release gate",
    "judge", "security review", "production approval",
)
WORKER_TRIGGERS = (
    "code", "function", "debug", "fix", "refactor", "implement", "bug", "error",
    "python", "javascript", "typescript", "api", "endpoint", "build", "deploy",
    "repo", "pull request", "commit", "branch", "database", "sql", "scrape",
    "browser", "tool", "workflow", "automation",
)
REASON_TRIGGERS = (
    "analyze", "plan", "reason", "decide", "architect", "design", "evaluate",
    "compare", "assess", "strategize", "research", "investigate", "optimize",
    "complex", "audit",
)


def _norm(message):
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def direct_response(message):
    """Return a truthful deterministic response when no model is useful."""
    return DIRECT_RESPONSES.get(_norm(message))


def classify_task(message):
    """Return (task_type, lane, max_tokens) without calling a model."""
    text = _norm(message)
    words = text.split()

    if direct_response(message) is not None:
        return "direct", "direct", 0

    if any(t in text for t in JUDGE_TRIGGERS):
        return "judge", "judge", LANES["judge"]["max_tokens"]

    risk = any(t in text for t in HIGH_RISK)
    reasoning = any(t in text for t in REASON_TRIGGERS)
    worker = any(t in text for t in WORKER_TRIGGERS)

    if risk or (reasoning and len(words) >= 28):
        return "reasoning", "reasoner", LANES["reasoner"]["max_tokens"]
    if worker:
        return "worker", "worker", LANES["worker"]["max_tokens"]
    if reasoning:
        return "reasoning_light", "worker", LANES["worker"]["max_tokens"]
    return "default", "flash", LANES["flash"]["max_tokens"]


def _gateway_env():
    if os.environ.get("AI_GATEWAY_API_KEY"):
        return "AI_GATEWAY_API_KEY"
    if os.environ.get("VERCEL_OIDC_TOKEN"):
        return "VERCEL_OIDC_TOKEN"
    return None


def _native_for_lane(lane):
    for model, base_url, env_key in NATIVE_FALLBACKS.get(lane, []):
        if os.environ.get(env_key):
            return model, base_url, env_key
    return None


def route_model(message):
    """Pick the fastest sufficient configured model; return None for static config fallback."""
    task_type, lane, max_tokens = classify_task(message)
    if lane == "direct":
        return None

    lane_cfg = LANES[lane]
    gateway_env = _gateway_env()
    if gateway_env:
        return {
            "model": lane_cfg["model"],
            "models": lane_cfg["fallbacks"],
            "base_url": GATEWAY_BASE,
            "api_key_env": gateway_env,
            "max_tokens": max_tokens,
            "task_type": task_type,
            "lane": lane,
            "strength": lane_cfg["strength"],
            "routing": "vercel-ai-gateway",
        }

    native = _native_for_lane(lane)
    if native:
        model, base_url, env_key = native
        return {
            "model": model,
            "models": [],
            "base_url": base_url,
            "api_key_env": env_key,
            "max_tokens": max_tokens,
            "task_type": task_type,
            "lane": lane,
            "strength": lane_cfg["strength"],
            "routing": "provider-native-fallback",
        }

    # Returning None deliberately tells server.py to use its already-configured
    # provider instead of sending an unrelated provider key to AI Gateway.
    return None


TOOL_REGISTRY = {
    "github": {"triggers": ["repo", "pr", "pull request", "commit", "branch", "issue", "merge", "github"], "env_keys": ["GH_PAT"], "description": "GitHub repo management, PRs, issues, commits", "module": "tools_github"},
    "firecrawl": {"triggers": ["scrape", "crawl", "website content", "research this site", "extract from url", "web data"], "env_keys": ["FIRECRAWL_API_TOKEN"], "description": "Web scraping and content extraction", "module": "tools_firecrawl"},
    "brightdata": {"triggers": ["bright data", "proxy", "serp", "search results", "google results"], "env_keys": ["BRIGHT_DATA_API"], "description": "Web search and data proxy", "module": "tools_brightdata"},
    "elevenlabs": {"triggers": ["voice", "speak", "tts", "say this", "narrate", "audio"], "env_keys": ["ELEVEN_LABS_API"], "description": "Voice synthesis (TTS)", "module": "tools_elevenlabs"},
    "fal_ai": {"triggers": ["generate image", "create image", "fal", "visual", "render image", "album art", "cover art"], "env_keys": ["FAL_AI_API"], "description": "Image generation (FAL)", "module": "tools_fal"},
    "heygen": {"triggers": ["video", "avatar video", "heygen", "talking head", "video message"], "env_keys": ["HEY_GEN_API"], "description": "AI video generation (HeyGen)", "module": "tools_heygen"},
    "runway": {"triggers": ["video edit", "runway", "video generation", "motion video"], "env_keys": ["RUNWAY_API_KEY"], "description": "Video generation (Runway)", "module": "tools_runway"},
    "youtube": {"triggers": ["youtube", "upload video", "transcript", "channel", "subscriber"], "env_keys": ["YOUTUBE_API_KEY"], "description": "YouTube management and transcripts", "module": "tools_youtube"},
    "supabase": {"triggers": ["database", "supabase", "query data", "sql", "table", "storage bucket"], "env_keys": ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"], "description": "Database and storage (Supabase)", "module": "tools_supabase"},
    "stripe": {"triggers": ["payment", "stripe", "charge", "subscription", "billing", "checkout"], "env_keys": ["STRIPE_SECRET_KEY"], "description": "Payments (Stripe) — DRAFT ONLY, never auto-charge", "module": "tools_stripe"},
    "coolify": {"triggers": ["deploy", "coolify", "container", "docker", "server", "vps"], "env_keys": ["COOLIFY_API_TOKEN", "COOLIFY_URL"], "description": "Deployment management (Coolify)", "module": "tools_coolify"},
    "cloudflare": {"triggers": ["dns", "cloudflare", "domain", "cdn", "ssl"], "env_keys": ["CLOUDFLARE_API_TOKEN"], "description": "DNS and CDN (Cloudflare)", "module": "tools_cloudflare"},
    "radio": {"triggers": ["radio", "dj", "azuracast", "playlist", "broadcast", "go live", "now playing", "culture shock", "trail mixx"], "env_keys": ["AZURACAST_API_KEY", "AZURACAST_URL"], "description": "Radio station management (AzuraCast) — Culture Shock Radio", "module": "tools_radio"},
    "notion": {"triggers": ["notion", "notes", "wiki", "knowledge base", "document"], "env_keys": ["NOTION_API_TOKEN"], "description": "Notion workspace (notes, docs)", "module": "tools_notion"},
    "twilio": {"triggers": ["call", "phone", "sms", "text message", "twilio"], "env_keys": ["TWILIO_ACCOUNT_SID", "TWILIO_SECRET"], "description": "Phone/SMS (Twilio)", "module": "tools_twilio"},
    "jcodemunch": {"triggers": ["index repo", "search code", "symbol", "function definition", "code search", "jcodemunch", "codebase scan"], "env_keys": [], "description": "Token-efficient code indexing and symbol search", "module": "tools_jcodemunch"},
    "rtk": {"triggers": [], "env_keys": [], "description": "RTK token compression (always active on I/O)", "module": "tools_rtk", "always_on": True},
}


def get_tools_for_task(message, mission_context=None):
    text = _norm(message)
    if mission_context:
        text += " " + _norm(mission_context)
    activated = []
    for tool_name, config in TOOL_REGISTRY.items():
        if config.get("always_on"):
            activated.append({"tool": tool_name, "description": config["description"], "activated": "always_on", "env_status": "n/a", "available": True, "module": config.get("module")})
            continue
        if any(t in text for t in config.get("triggers", [])):
            env_status = {ek: ("present" if os.environ.get(ek) else "missing") for ek in config.get("env_keys", [])}
            activated.append({
                "tool": tool_name,
                "description": config["description"],
                "activated": "matched",
                "env_status": env_status,
                "available": all(v == "present" for v in env_status.values()) if env_status else True,
                "module": config.get("module"),
            })
    return activated


def get_tool_status():
    status = []
    for tool_name, config in TOOL_REGISTRY.items():
        env_status = {ek: ("present" if os.environ.get(ek) else "missing") for ek in config.get("env_keys", [])}
        status.append({
            "tool": tool_name,
            "description": config["description"],
            "connected": all(v == "present" for v in env_status.values()) if env_status else True,
            "always_on": config.get("always_on", False),
            "env_keys": list(env_status.keys()),
            "env_status": env_status,
        })
    return status


def bars_route(message, mission_context=None):
    direct = direct_response(message)
    if direct is not None:
        return {"cached": direct, "cache_hit": True, "model": None, "tools": [], "task_type": "direct", "lane": "direct"}

    task_type, lane, _ = classify_task(message)
    model_info = route_model(message)
    return {
        "cached": None,
        "cache_hit": False,
        "model": model_info,
        "tools": get_tools_for_task(message, mission_context),
        "task_type": task_type,
        "lane": lane,
    }


if __name__ == "__main__":
    tests = [
        "ok",
        "summarize this note",
        "fix this TypeScript endpoint",
        "analyze the production architecture and rollback risk",
        "run the final independent security review before release",
    ]
    for msg in tests:
        print(msg, "=>", bars_route(msg))
