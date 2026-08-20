# BARS / TARS Dependencies & Ecosystem

## Runtime Dependencies
- **Python**: 3.10+ (Tested on Python 3.13)
- **Node.js**: 20+ (for Gemini CLI and Terabithia bridge)
- **Core Python Packages**:
  - `anthropic` (Claude API client)
  - `google-genai` / `@google/gemini-cli` (Gemini model execution)
  - `requests` / `urllib` (HTTP networking)
  - `websockets` (Realtime voice and streaming)
  - `pydantic` (Data models)

## External Services
- **Terabithia Control Plane**: `https://api.thepaulieffect.com/terabithia`
- **ElevenLabs**: Voice streaming synthesis (`api.elevenlabs.io`)
- **Supabase / PostgreSQL**: Evidence layer (`31.220.58.212:5434`)
- **Vercel**: Public web frontend hosting (`tars-agent.vercel.app`)
