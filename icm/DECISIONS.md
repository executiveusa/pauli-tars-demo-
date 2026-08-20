# BARS / TARS Architectural Decisions

## ADR-001: Sovereign Outbound Polling Pattern
- **Context**: BARS runs on a Windows workstation behind a consumer NAT / firewall without a static public IP.
- **Decision**: Worker initiates outbound long-polling / regular polling to Terabithia `/api/v1/operators/bars/missions/poll` rather than exposing an inbound web hook.
- **Consequences**: Zero open ports on the client machine; immune to inbound internet scanning.

## ADR-002: Dual-Mode Evidence Persistence
- **Context**: Supabase connection pooler on VPS might experience network latency or isolation.
- **Decision**: `DeploymentEvidenceStore` provides dual-mode persistence (PostgreSQL Supavisor pooler + in-memory store) ensuring non-blocking operations.

## ADR-003: 5-Lane Router Architecture
- **Context**: Different queries require varying levels of capability and latency.
- **Decision**: `bars_router.py` classifies prompts into `DIRECT`, `FLASH`, `WORKER`, `REASONER`, or `JUDGE`, with support for manual UI model selection.
