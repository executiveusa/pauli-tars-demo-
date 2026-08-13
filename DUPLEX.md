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

`server.py` starts an OpenAI-compatible brain at **http://127.0.0.1:4323** (`POST /v1/chat/completions`, streaming supported), locked behind the Bearer token in `bars-duplex.json`.

For backward compatibility during migration, a runtime may read a legacy `tars-duplex.json` once, but new state must be written under the BARS name. Remove the legacy file after the migration is verified.

**Do not expose port 4321 publicly.** If remote access is required, expose only the narrow token-gated interface and apply the normal security review.

## ElevenLabs custom-LLM setup

1. Tunnel only the duplex endpoint you intend to expose, for example `http://localhost:4323`.
2. In ElevenLabs Agents, create/configure the agent using the tunnel URL ending in `/v1`.
3. Use the token value from `bars-duplex.json` as the API credential.
4. Use model id `bars`.
5. First message: `BARS online. Talk.`
6. Save the ElevenLabs agent id to `config.json -> elevenlabs.agent_id` and restart BARS.

## Wake word

`config.example.json` contains the Picovoice scaffold. The intended trained wake phrase is **“Hey BARS”**. Keep the ordinary speech-to-text fallback so the product remains usable without a paid/custom wake-word setup.

Related fleet layers: **BARS · Jarvis · Hermes · Pi · Lightning**.
