# BARS / TARS Sovereign Deployment Blueprint

## SOURCE
- Canonical Repository: `https://github.com/executiveusa/pauli-tars-demo-.git`
- Base Commit SHA: `740a124`
- Local Worktree: `C:\Users\execu\pauli-local\tars`

## TARGETS
- **Control Plane**: Hostinger VPS (`srv1099662.hstgr.cloud` / `31.220.58.212`)
- **Public Frontend**: Vercel (`tars-agent.vercel.app`)
- **Worker Host**: `TABLET-RV7J0DA1` (Node ID: `bambu-windows-01`)

## DATA AUTHORITY
- Canonical Mission & Policy Authority: **Terabithia**
- Telemetry & Evidence Store: **Supabase / PostgreSQL**
- Local Execution State: **`tars-state.json`**

## TERABITHIA CONTRACT
- Base Route: `/api/v1/operators/bars/*`
- Mission Endpoints:
  - `POST /api/v1/operators/bars/missions` (Authority Enqueue)
  - `GET /api/v1/operators/bars/missions/poll` (Worker Poll)
  - `POST /api/v1/operators/bars/missions/:id/claim` (Worker Claim)
  - `POST /api/v1/operators/bars/missions/:id/progress` (Worker Progress)
  - `POST /api/v1/operators/bars/missions/:id/report` (Terminal Evidence Report)
  - `POST /api/v1/operators/bars/heartbeat` (Worker Heartbeat)

## VPS SERVICES
- `terabithia-bridge`: Docker container on port 3000 (proxied via Caddy on 443)
- `hermes.service`: systemd service on port 4800
- `supabase-db`: PostgreSQL / Supavisor pooler on port 5434

## VERCEL FRONTEND
- Project: `tars-agent`
- Domain: `https://tars-agent.vercel.app`
- Status Endpoint: `/api/status`
- Web Chat & Voice Interface: `/`

## MODEL PROVIDERS
- Anthropic Claude (`claude-3-5-sonnet`, `claude-3-5-haiku`)
- Google Gemini (`gemini-2.5-flash`, `gemini-2.5-pro`)
- OpenAI / OpenRouter (`o3-mini`, `gpt-4o-mini`)
- DeepSeek (`deepseek-r1`)

## ELEVENLABS
- Voice ID: Configured in `config.json` / `COSMOS.ENV`
- Integration: Low-latency streaming WebSocket synthesis

## WORKER NODE
- Node ID: `bambu-windows-01`
- Polling Script: `bars_terabithia_bridge.py`
- Local Mission Storage: `missions/<id>/report.md`

## ENV VARIABLE NAMES (Zero Values Disclosed)
- `TERABITHIA_REMOTE_URL`
- `TERABITHIA_API_KEY`
- `BARS_REMOTE_TOKEN`
- `BARS_NODE_ID`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `ELEVEN_LABS_API`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## HEALTH ENDPOINTS
- Terabithia Public Health: `GET https://api.thepaulieffect.com/terabithia/health`
- Vercel Public Status: `GET https://tars-agent.vercel.app/api/status`
- Local BARS Status: `GET http://127.0.0.1:4321/api/status`

## PRIMARY WALKTEST
- Full lifecycle verification:
  1. Mission enqueued on Terabithia
  2. Claimed by `bambu-windows-01`
  3. Local inspection executed
  4. Terminal evidence reported
  5. Receipt stored in Supabase

## ROLLBACK
- Terabithia rollback SHA: `398f113`
- BARS rollback SHA: `ee395bf`
