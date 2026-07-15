# TARS Live Voice — real-time conversation (📡)

Turn-based voice (wake word / hands-free) works out of the box. The **📡 LIVE**
button gives TARS a real phone-call feel: sub-second turns, natural
interruptions, no wake word. Two engines:

## Engine A — GPT Realtime (WIRED, default) ✅

The 📡 LIVE button runs **OpenAI Realtime over WebRTC** — browser talks straight
to OpenAI, so latency is minimal and you can talk over him. TARS's persona (with
your humor/honesty dials + long-term memory) is loaded as the session
instructions, and he has two live tools: **deploy_mission** (say "go research…"
/ "build me…" and a robot spins up mid-call) and **remember**.

- **Key:** uses `openai.api_key` from `config.json`, or **borrows the Jarvis
  OpenAI key** automatically (read-only fallback). Nothing to set up if Jarvis is
  configured — the button just works.
- **Voice while live:** an OpenAI voice (`ash` by default — deep, dry; change
  `openai.realtime_voice` in config). NOT the ElevenLabs voice — Realtime uses
  OpenAI's own TTS. Turn-based replies still use your ElevenLabs pick.
- **Needs:** an OpenAI key with Realtime access, mic permission for the site,
  and a Chromium browser. Server endpoint: `POST /api/realtime_session`.

That's it — press 📡 LIVE and talk.

## Engine B — ElevenLabs Agents (optional, keeps the ElevenLabs voice)

Only used if there's NO OpenAI key but an `elevenlabs.agent_id` is set. Gives the
full-duplex feel while keeping TARS's ElevenLabs voice, using **TARS's own Claude
brain** via the token-gated bay below (the server keeps thinking; ElevenLabs does
ears + mouth). Same pattern as the [[Jarvis]] duplex bay.

## What's already running

`server.py` starts an OpenAI-compatible brain at **http://127.0.0.1:4323**
(`POST /v1/chat/completions`, streaming supported), locked behind the Bearer
token in `tars-duplex.json` (auto-generated, gitignored). TARS persona + dials
+ long-term memory are applied server-side.

**Never tunnel port 4321** (the full assistant). Only 4323 — it exposes exactly
one token-gated chat route.

## Setup (one time, ~10 minutes)

1. **Tunnel the brain:**
   `cloudflared tunnel --url http://localhost:4323`
   → note the `https://….trycloudflare.com` URL.
2. **ElevenLabs dashboard → Agents → New agent:**
   - Voice: **Roger** (`CwhRBWXzGAHq8TQ4Fs17`)
   - LLM: **Custom LLM** → Server URL `https://<tunnel>/v1`,
     API key = the `token` value from `tars-duplex.json`, model id `tars`.
   - First message: "TARS online. Talk."
   - (Requires an ElevenLabs key WITH the Agents scope — same caveat as Jarvis.)
3. **Paste the agent id** into `config.json → elevenlabs.agent_id`.
4. Restart TARS. The **📡 LIVE** button appears in the HUD and opens the
   embedded ElevenLabs call widget — full duplex, barge-in native.

## Custom wake word (Picovoice scaffold — item #13)

`config.example.json` has a `picovoice` block. To use a REAL trained
"Hey TARS" wake word instead of the fuzzy speech-to-text matching:
get a free access key at console.picovoice.ai, train a "Hey TARS" keyword
(Porcupine → Web WASM), drop the `.ppn` in `static/`, and fill the block.
The fuzzy WAKE regex remains the zero-setup fallback.

Related: [[TARS]] · [[Jarvis]] · [[AI Workshop]]
