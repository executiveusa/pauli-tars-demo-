# BARS / TARS Current State

## Operational Status
- **Canonical Repository**: `https://github.com/executiveusa/pauli-tars-demo-.git`
- **Active Branch**: `main`
- **Head SHA**: `740a124` (with local bridge adapter additions)
- **Local Runtime**: Python 3.13 on `bambu-windows-01` (`C:\Users\execu\pauli-local\tars`)
- **Remote Public Web**: `https://tars-agent.vercel.app`
- **Control Plane Gateway**: `https://api.thepaulieffect.com/terabithia`
- **Worker Node Status**: `ONLINE` / `ATTACHED` via outbound polling runner (`bars_terabithia_bridge.py`)

## Verified Capabilities
- [x] Outbound Terabithia polling, claiming, progress reporting, and terminal evidence submission.
- [x] Proof mission `bars_ms_1787194081117_ziohzo` executed locally as `bars_loc_20ace583` and verified.
- [x] 5-Lane Model Router in `bars_router.py` with automatic latency and token optimization.
- [x] ElevenLabs voice streaming engine.
- [x] Constrained OpenCode / coding-agent executor.
