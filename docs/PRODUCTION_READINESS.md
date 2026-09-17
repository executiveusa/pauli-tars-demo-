# BARS Production Readiness

## Current state

BARS web/API facade is merged to `main` and can delegate chat and long-running work to a Hermes runtime when `HERMES_REMOTE_URL` and `HERMES_API_KEY` are configured.

Production-ready requires four phases. Each phase must produce evidence before the next release boundary is considered complete.

## Phase 1 — Hermes Runtime Attachment

Outcome: BARS talks to a persistent, current Hermes runtime rather than demo/fallback logic.

Required work:
- install current `NousResearch/hermes-agent` on a persistent host
- apply `scripts/build-bars-hermes-runtime.sh`
- enable Hermes API server
- create a dedicated BARS API key
- expose Hermes through TLS without publishing credentials
- configure `HERMES_REMOTE_URL` and `HERMES_API_KEY` on the BARS deployment
- keep Terabithia fallback intact until Hermes path is proven

Proof gate:
- `/api/capabilities` reports Hermes reachable
- `/api/status` reports Hermes attached
- BARS chat returns a real Hermes response
- `/v1/runs` accepts one safe read-only mission
- evidence includes request id/run id and terminal status

## Phase 2 — Tool + App Capability Pack

Outcome: BARS can use the same operational surface as Hermes for artist/product work.

Required capability groups:
- GitHub repository read/write through approved credentials
- browser/web research
- Composio tool discovery and OAuth connections
- Google Drive file discovery/read/write through user-approved connection
- media adapters: OpenSuno plus verified image/video providers
- interactive-artifact and website/store creation skills
- explicit provider registry so integrations remain replaceable

Proof gate:
- one test per capability group
- no secrets in repo/logs
- destructive actions remain approval-gated
- disconnected providers degrade truthfully

## Phase 3 — Artist Production Loop

Outcome: one mission can move from brief to verified artist deliverable.

Canonical test mission:
1. ingest an artist brief and approved Drive assets
2. research references
3. generate or ingest music assets
4. create visual direction
5. produce a video/interactive artifact/store slice
6. run builder + independent critic loop
7. save deliverables and provenance
8. return a proof-backed handoff

Proof gate:
- complete sandbox run
- all tool calls traceable
- generated artifacts accessible
- critic is independent from builder
- user can interrupt, approve, retry and rollback

## Phase 4 — Production Hardening + Release

Outcome: BARS can be exposed to real users without confusing availability with correctness.

Required work:
- authentication and least privilege
- rate limits and budget caps
- persistent audit/receipt trail
- error handling and provider fallback
- observability for chat/runs/tool failures
- recovery from worker restart
- secret scan
- dependency/security review
- production smoke suite
- documented rollback to prior Vercel deployment and prior Hermes runtime release

Proof gate:
- security review pass
- reliability review pass
- ownership/sovereignty review pass
- rollback drill pass
- production smoke suite pass
- final human release approval

## Release rule

A green build is not production proof. BARS is production-ready only when all four proof gates are satisfied with observable evidence.
