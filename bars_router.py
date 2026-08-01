"""
BARS Auto-Router + Lazy Tool Loader
====================================
The user just sees work getting done. Behind the scenes:

1. AUTO-ROUTER: classifies each incoming message by task type,
   picks the fastest sufficient model, adjusts max_tokens.
   Cost-aware: free models first, paid only when needed.

2. LAZY TOOL LOADER: all integrations stay "connected" (config available)
   but only ACTIVATE when a mission needs them. No tool loads unless
   the task requires it. Keeps context lean, latency low.

Integration with BARS server.py:
    from bars_router import route_model, get_tools_for_task
    model_choice = route_model(user_message)
    tools = get_tools_for_task(user_message, mission_context)
"""

import json
import os
import re
import time
from pathlib import Path

# ─── Model Registry (cost-aware, speed-ranked) ───────────────────────────────

MODELS = {
    # FREE models (always prefer first)
    "groq-8b": {
        "id": "llama-3.1-8b-instant",
        "base_url": "https://api.groq.com/openai/v1",
        "cost": 0.0,
        "speed": 0.3,
        "max_tokens": 300,
        "strength": "fast_ack",
        "env_key": "GROQ_API_KEY",
    },
    "groq-70b": {
        "id": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "cost": 0.0,
        "speed": 0.8,
        "max_tokens": 600,
        "strength": "balanced",
        "env_key": "GROQ_API_KEY",
    },
    "mercury-2": {
        "id": "mercury-2",
        "base_url": "https://api.inceptionlabs.ai/v1",
        "cost": 0.0,
        "speed": 0.5,
        "max_tokens": 800,
        "strength": "diffusion_fast",
        "env_key": "MERCURY2_API_TOKEN",
    },
    "groq-qwen": {
        "id": "groq/qwen3-32b",
        "base_url": "https://api.groq.com/openai/v1",
        "cost": 0.0,
        "speed": 0.6,
        "max_tokens": 600,
        "strength": "code_bulk",
        "env_key": "GROQ_API_KEY",
    },
    # PAID models (use only when free can't handle it)
    "openrouter-deepseek": {
        "id": "deepseek/deepseek-chat-v3.1",
        "base_url": "https://openrouter.ai/api/v1",
        "cost": 0.001,  # per 1k tokens approx
        "speed": 1.2,
        "max_tokens": 1000,
        "strength": "deep_reasoning",
        "env_key": "OPEN_ROUTER_API",
    },
    "openrouter-hermes3": {
        "id": "openrouter/nousresearch/hermes-3-llama-3.1-405b:free",
        "base_url": "https://openrouter.ai/api/v1",
        "cost": 0.0,
        "speed": 2.0,
        "max_tokens": 1000,
        "strength": "deepest_free",
        "env_key": "OPEN_ROUTER_API",
    },
}

# ─── Task Classifier ─────────────────────────────────────────────────────────

TASK_PATTERNS = {
    "quick_ack": {
        "keywords": ["ok", "yes", "no", "thanks", "hello", "hi", "status", "online", "acknowledge", "got it", "cool"],
        "max_words": 12,
        "has_question": False,
        "model": "groq-8b",
        "max_tokens": 150,
    },
    "code": {
        "keywords": ["code", "function", "debug", "fix", "refactor", "implement", "bug", "error", "python", "javascript", "typescript", "api", "endpoint", "build", "deploy"],
        "model": "groq-70b",
        "max_tokens": 600,
    },
    "code_bulk": {
        "keywords": ["batch", "bulk", "process data", "extract", "parse", "transform", "convert", "cleanup", "normalize", "summarize all"],
        "model": "groq-qwen",
        "max_tokens": 600,
    },
    "creative": {
        "keywords": ["write", "draft", "compose", "create content", "story", "copy", "blog", "email", "message", "marketing", "script", "rhyme", "verse", "bar"],
        "model": "groq-70b",
        "max_tokens": 600,
    },
    "reasoning": {
        "keywords": ["analyze", "plan", "reason", "decide", "architect", "design", "evaluate", "compare", "assess", "strategize", "think", "music theory", "produce", "mix", "compose"],
        "model": "mercury-2",
        "max_tokens": 800,
    },
    "deep_reasoning": {
        "keywords": ["research", "investigate", "complex", "algorithm", "optimize", "security", "audit", "architecture decision"],
        "min_words": 40,
        "model": "openrouter-deepseek",
        "max_tokens": 1000,
    },
    "radio_dj": {
        "keywords": ["radio", "dj", "mix", "playlist", "show", "broadcast", "stream", "azuracast", "culture shock", "trail mixx show", "now playing", "go live"],
        "model": "groq-70b",
        "max_tokens": 600,
    },
    "default": {
        "model": "groq-70b",
        "max_tokens": 400,
    },
}


def classify_task(message):
    """Classify an incoming message → (task_type, model_key, max_tokens)."""
    text = (message or "").lower().strip()
    words = text.split()
    word_count = len(words)
    has_question = "?" in text

    # Score each task type (excluding default)
    scores = {}
    for task_type, config in TASK_PATTERNS.items():
        if task_type == "default":
            continue
        score = 0

        # Keyword matching (strong signal)
        keywords = config.get("keywords", [])
        kw_hits = sum(1 for kw in keywords if kw in text)
        score += kw_hits * 3

        # Word count constraints (weak signal)
        max_words = config.get("max_words")
        if max_words and word_count <= max_words:
            score += 1
        min_words = config.get("min_words")
        if min_words and word_count >= min_words:
            score += 2

        # Question constraint
        if config.get("has_question") is False and not has_question:
            score += 1

        scores[task_type] = score

    # Find best non-quick_ack match first
    best_type = None
    best_score = 0
    for t, s in scores.items():
        if t == "quick_ack":
            continue
        if s > best_score:
            best_score = s
            best_type = t

    # Only fall back to quick_ack if nothing else scored AND quick_ack scored
    if not best_type or best_score == 0:
        if scores.get("quick_ack", 0) > 0:
            best_type = "quick_ack"
            best_score = scores["quick_ack"]

    if not best_type:
        best_type = "default"

    config = TASK_PATTERNS[best_type]
    model_key = config["model"]
    max_tokens = config.get("max_tokens", 400)

    return best_type, model_key, max_tokens


def route_model(message):
    """
    Main entry: takes a user message, returns the optimal model config.
    Returns: {model, base_url, api_key_env, max_tokens, task_type, cost_estimate}
    """
    task_type, model_key, max_tokens = classify_task(message)
    model_config = MODELS[model_key]

    return {
        "model": model_config["id"],
        "base_url": model_config["base_url"],
        "api_key_env": model_config["env_key"],
        "max_tokens": max_tokens,
        "task_type": task_type,
        "cost_per_1k": model_config["cost"],
        "speed_estimate": model_config["speed"],
        "strength": model_config["strength"],
    }


# ─── Lazy Tool Loader ────────────────────────────────────────────────────────

# Each tool is "connected" (config available) but only activates when needed.
# This keeps BARS's context lean — he doesn't carry 50 tool definitions
# when he only needs 2 for the current mission.

TOOL_REGISTRY = {
    "github": {
        "triggers": ["repo", "pr", "pull request", "commit", "branch", "issue", "merge", "github"],
        "env_keys": ["GH_PAT"],
        "description": "GitHub repo management, PRs, issues, commits",
        "module": "tools_github",
    },
    "firecrawl": {
        "triggers": ["scrape", "crawl", "website content", "research this site", "extract from url", "web data"],
        "env_keys": ["FIRECRAWL_API_TOKEN"],
        "description": "Web scraping and content extraction",
        "module": "tools_firecrawl",
    },
    "brightdata": {
        "triggers": ["bright data", "proxy", "serp", "search results", "google results"],
        "env_keys": ["BRIGHT_DATA_API"],
        "description": "Web search and data proxy",
        "module": "tools_brightdata",
    },
    "elevenlabs": {
        "triggers": ["voice", "speak", "tts", "say this", "narrate", "audio"],
        "env_keys": ["ELEVEN_LABS_API"],
        "description": "Voice synthesis (TTS)",
        "module": "tools_elevenlabs",
    },
    "fal_ai": {
        "triggers": ["generate image", "create image", "fal", "visual", "render image", "album art", "cover art"],
        "env_keys": ["FAL_AI_API"],
        "description": "Image generation (FAL)",
        "module": "tools_fal",
    },
    "heygen": {
        "triggers": ["video", "avatar video", "heygen", "talking head", "video message"],
        "env_keys": ["HEY_GEN_API"],
        "description": "AI video generation (HeyGen)",
        "module": "tools_heygen",
    },
    "runway": {
        "triggers": ["video edit", "runway", "video generation", "motion video"],
        "env_keys": ["RUNWAY_API_KEY"],
        "description": "Video generation (Runway)",
        "module": "tools_runway",
    },
    "youtube": {
        "triggers": ["youtube", "upload video", "transcript", "channel", "subscriber"],
        "env_keys": ["YOUTUBE_API_KEY"],
        "description": "YouTube management and transcripts",
        "module": "tools_youtube",
    },
    "supabase": {
        "triggers": ["database", "supabase", "query data", "sql", "table", "storage bucket"],
        "env_keys": ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"],
        "description": "Database and storage (Supabase)",
        "module": "tools_supabase",
    },
    "stripe": {
        "triggers": ["payment", "stripe", "charge", "subscription", "billing", "checkout"],
        "env_keys": ["STRIPE_SECRET_KEY"],
        "description": "Payments (Stripe) — DRAFT ONLY, never auto-charge",
        "module": "tools_stripe",
    },
    "coolify": {
        "triggers": ["deploy", "coolify", "container", "docker", "server", "vps"],
        "env_keys": ["COOLIFY_API_TOKEN", "COOLIFY_URL"],
        "description": "Deployment management (Coolify)",
        "module": "tools_coolify",
    },
    "cloudflare": {
        "triggers": ["dns", "cloudflare", "domain", "cdn", "ssl"],
        "env_keys": ["CLOUDFLARE_API_TOKEN"],
        "description": "DNS and CDN (Cloudflare)",
        "module": "tools_cloudflare",
    },
    "radio": {
        "triggers": ["radio", "dj", "azuracast", "playlist", "broadcast", "go live", "now playing", "culture shock", "trail mixx"],
        "env_keys": ["AZURACAST_API_KEY", "AZURACAST_URL"],
        "description": "Radio station management (AzuraCast) — Culture Shock Radio",
        "module": "tools_radio",
    },
    "notion": {
        "triggers": ["notion", "notes", "wiki", "knowledge base", "document"],
        "env_keys": ["NOTION_API_TOKEN"],
        "description": "Notion workspace (notes, docs)",
        "module": "tools_notion",
    },
    "twilio": {
        "triggers": ["call", "phone", "sms", "text message", "twilio"],
        "env_keys": ["TWILIO_ACCOUNT_SID", "TWILIO_SECRET"],
        "description": "Phone/SMS (Twilio)",
        "module": "tools_twilio",
    },
    "jcodemunch": {
        "triggers": ["index repo", "search code", "symbol", "function definition", "code search", "jcodemunch", "codebase scan"],
        "env_keys": [],
        "description": "Token-efficient code indexing and symbol search",
        "module": "tools_jcodemunch",
    },
    "rtk": {
        "triggers": [],  # Always available as compression layer, no trigger needed
        "env_keys": [],
        "description": "RTK token compression (always active on I/O)",
        "module": "tools_rtk",
        "always_on": True,
    },
}


def get_tools_for_task(message, mission_context=None):
    """
    Lazy-load tools for a specific task.
    Returns: list of {tool_name, description, available, env_status}
    Only tools whose triggers match the message are activated.
    """
    text = (message or "").lower()
    if mission_context:
        text += " " + mission_context.lower()

    activated = []
    for tool_name, config in TOOL_REGISTRY.items():
        # Always-on tools (like RTK compression)
        if config.get("always_on"):
            activated.append({
                "tool": tool_name,
                "description": config["description"],
                "activated": "always_on",
                "env_status": "n/a",
            })
            continue

        # Check triggers
        triggers = config.get("triggers", [])
        matched = any(t in text for t in triggers)

        if matched:
            # Check env keys are available
            env_status = {}
            for ek in config.get("env_keys", []):
                val = os.environ.get(ek, "")
                env_status[ek] = "present" if val and len(val) > 5 else "missing"

            all_present = all(v == "present" for v in env_status.values()) if env_status else True

            activated.append({
                "tool": tool_name,
                "description": config["description"],
                "activated": "matched",
                "env_status": env_status,
                "available": all_present,
                "module": config.get("module"),
            })

    return activated


def get_tool_status():
    """Return full status of ALL tools (connected, not just activated)."""
    status = []
    for tool_name, config in TOOL_REGISTRY.items():
        env_status = {}
        for ek in config.get("env_keys", []):
            val = os.environ.get(ek, "")
            env_status[ek] = "present" if val and len(val) > 5 else "missing"

        all_present = all(v == "present" for v in env_status.values()) if env_status else True

        status.append({
            "tool": tool_name,
            "description": config["description"],
            "connected": all_present,
            "always_on": config.get("always_on", False),
            "env_keys": list(env_status.keys()),
            "env_status": env_status,
        })
    return status


# ─── Response Cache (simple in-memory LRU) ───────────────────────────────────

_cache = {}
_cache_order = []
_CACHE_MAX = 50


def cache_get(key):
    """Check if we have a cached response for this message."""
    normalized = re.sub(r"\s+", " ", (key or "").lower().strip())[:200]
    if normalized in _cache:
        return _cache[normalized]
    return None


def cache_set(key, value):
    """Cache a response."""
    normalized = re.sub(r"\s+", " ", (key or "").lower().strip())[:200]
    if normalized not in _cache:
        _cache_order.append(normalized)
        if len(_cache_order) > _CACHE_MAX:
            old = _cache_order.pop(0)
            _cache.pop(old, None)
    _cache[normalized] = value


# ─── Main BARS Router Function ───────────────────────────────────────────────

def bars_route(message, mission_context=None):
    """
    The single function BARS calls before processing any message.
    Returns everything BARS needs: model choice, activated tools, cache check.

    Usage in server.py:
        from bars_router import bars_route
        route = bars_route(user_message)
        if route["cached"]:
            return route["cached"]
        # use route["model"] for the LLM call
        # route["tools"] tells you which tools are activated for this task
    """
    # Check cache first
    cached = cache_get(message)
    if cached:
        return {
            "cached": cached,
            "model": None,
            "tools": [],
            "task_type": "cache_hit",
            "cache_hit": True,
        }

    # Route model
    model_info = route_model(message)

    # Get tools
    tools = get_tools_for_task(message, mission_context)

    return {
        "cached": None,
        "cache_hit": False,
        "model": model_info,
        "tools": tools,
        "task_type": model_info["task_type"],
    }


if __name__ == "__main__":
    # Self-test
    tests = [
        ("ok", "quick ack"),
        ("Build me a landing page for the Trail Mixx snack brand", "code"),
        ("Analyze the beat structure of this track and suggest improvements", "reasoning"),
        ("Write a 16-bar verse about Northwest fruits for the Trail Mixx campaign", "creative"),
        ("Go live on Culture Shock Radio and play the new mix", "radio_dj"),
        ("Research the history of battle rap and write a detailed analysis", "deep_reasoning"),
        ("Scrape this website and extract the product data: example.com", "code + firecrawl"),
    ]

    print("BARS Auto-Router Self-Test")
    print("=" * 60)
    for msg, expected in tests:
        route = bars_route(msg)
        m = route["model"]
        tools = [t["tool"] for t in route["tools"]]
        print(f"\nMessage: {msg[:60]}")
        print(f"  Expected: {expected}")
        print(f"  Task type: {route['task_type']}")
        print(f"  Model: {m['model']} ({m['strength']}, {m['speed_estimate']}s, ${m['cost_per_1k']}/1k)")
        print(f"  Max tokens: {m['max_tokens']}")
        print(f"  Tools activated: {tools or 'none'}")
