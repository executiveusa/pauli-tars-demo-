# BARS Finish Checklist

## Mission
Finish BARS as the long-running computer/media/operator agent while preserving truthful status, safe execution, and Trail Mixx as a product/domain rather than a sixth agent.

## Locked role
BARS performs computer operation, browser/desktop execution, media workflows, Trail Mixx operations, and long-running operator missions delegated by Hermes.

## Checklist
- [ ] Record current `main` SHA and baseline.
- [ ] Preserve BARS identity migration; legacy TARS names remain compatibility-only.
- [ ] Finish and verify interactive 3D front door.
- [ ] Desktop visual QA passes.
- [ ] Mobile visual QA passes.
- [ ] Reduced-motion/WebGL fallback passes.
- [ ] STATUS reads real `/api/status` or fails truthfully.
- [ ] JOBS reads real `/missions` or fails truthfully.
- [ ] TALK/MISSION/BUILD route to real agent paths.
- [ ] No write action occurs from landing page without explicit intent.
- [ ] Finish Trail Mixx read-only adapter server wiring.
- [ ] Add/verify `/api/trailmix/nowplaying` or equivalent canonical read endpoint.
- [ ] Keep Trail Mixx base URL owner-configured; never accept arbitrary request URL.
- [ ] Run deterministic adapter tests and CI.
- [ ] Do not claim Trail Mixx connectivity until live base URL is configured and proven.
- [ ] Keep Phase 3 Trail Mixx writes/queue/scheduling/publishing separately approval-gated.
- [ ] Define Windows computer-use worker contract for long-running desktop tasks.
- [ ] Capture screenshots/logs/evidence for operator missions.
- [ ] Add pause/resume/cancel and idempotency for long-running jobs.
- [ ] Preserve mission/evidence IDs from Hermes through execution.
- [ ] Run one golden path: Hermes mission -> BARS -> computer/tool action -> evidence -> result.
- [ ] Independent review passes before merge/deploy.

## Definition of done
BARS is finished when the identity migration is complete, front door is visually proven, Trail Mixx read path is real and truthful, long-running computer missions are resumable and observable, and Hermes can delegate a real operator task with evidence returned end to end.
