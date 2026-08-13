# BARS Live Voice — real-time conversation (📡)

Turn-based voice works out of the box. The **📡 LIVE** button gives BARS a real phone-call feel: sub-second turns, natural interruptions, and no wake word. Two engines are supported.

## Engine A — GPT Realtime (wired default)

The 📡 LIVE button uses **OpenAI Realtime over WebRTC**. The browser talks directly to OpenAI for low latency and barge-in. BARS's persona, current flavor/authenticity settings, and bounded context are loaded as session instructions. Live tools include mission deployment and memory capture.

- **Key:** uses `openai.api_key` from `config.json`, with the existing Jarvis read-only fallback where configured.
- **Voice:** OpenAI Realtime voice during the live session. Turn-based replies may use ElevenLabs or browser speech.
- **Needs:** Realtime-capable OpenAI key, microphone permission, and a compatible browser.
- **Server endpoint:** `POST /api/realtime_session`.

## Engine B — ElevenLabs Agents (optional)

Used when the ElevenLabs agent path is configured. It keeps BARS's ElevenLabs voice while the local BARS runtime remains the reasoning backend.

## Local duplex brain

`server.py` starts an OpenAI-compatible brain at **http://127.0.0.1:4323** (`POST /v1/chat/completions`, streaming supported).

### Current compatibility filename

The current runtime still stores its local duplex token in `tars-duplex.json`. This is a legacy internal filename only; the product/agent identity is BARS. Do not rename the file in documentation ahead of the runtime migration, because that would make setup instructions false.

The planned runtime cleanup is:

1. add canonical `bars-duplex.json`, `bars-state.json`, and `bars-memory.md` paths;
2. read legacy `tars-*` files only as one-time migration fallbacks;
3. write all new state under `bars-*`;
4. verify restart/resume behavior;
5. remove legacy files only after migration proof.

**Do not expose port 4321 publicly.** If remote access is required, expose only the narrow token-gated interface and apply the normal security review.

## ElevenLabs custom-LLM setup

1. Tunnel only the duplex endpoint you intend to expose, for example `http://localhost:4323`.
2. In ElevenLabs Agents, configure the custom LLM with the tunnel URL ending in `/v1`.
3. Until the runtime-path migration lands, use the token from `tars-duplex.json`.
4. Use model id `bars`.
5. First message: `BARS online. Talk.`
6. Save the ElevenLabs agent id to `config.json -> elevenlabs.agent_id` and restart BARS.

## Wake word

`config.example.json` contains the Picovoice scaffold. The intended trained wake phrase is **“Hey BARS”**. Keep the ordinary speech-to-text fallback so the product remains usable without a paid/custom wake-word setup.

Related fleet layers: **BARS · Jarvis · Hermes · Pi · Lightning**.
