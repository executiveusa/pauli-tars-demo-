# TARS 3D Front Door + Trail Mix Adapter Spec

## Product role
TARS is the bounded operator and public character. The landing page is the front door to the real TARS backend, not a separate mock product.

Trail Mix is TARS's music/radio domain. Source engine: `executiveusa/trail-mixx-source-code` (AzuraCast fork, AGPL-3.0).

## Current baseline
The repo already contains a Python TARS backend (`server.py`), computer-use implementation (`hands.py`), presence logic (`presence.py`), and a large Three.js browser experience under `static/index.html` with bundled `static/three.min.js`.

The current production Vercel deployment is tied to this repo. The latest deployment metadata includes a prior BARS rebrand commit, while the repository README still defines the product as TARS. This identity drift must be removed: the public product for this branch is TARS.

## Front-end rule
No stock robot.

If an owned Spline TARS scene is supplied later, the Spline React component may become the renderer. Until then, the production implementation should use the repo's existing Three.js stack to construct an original TARS-inspired monolith/operator body programmatically so the interaction does not depend on a third-party stock scene.

## Interaction contract
Desktop: pointer position influences key light/look direction and hover state.
Mobile: touch targets are explicit, large, and do not depend on hover.
Reduced-motion: all actions remain available without continuous animation.

Hotspots:

| Body region | UI label | Contract | Risk |
|---|---|---|---|
| visor/head | TALK | open voice/chat ingress | read/draft |
| chest | MISSION | create/brief a TARS mission | governed |
| left arm | TRAIL MIX | open Trail Mix controls/read station state | read first |
| right arm | BUILD | bounded computer-use/build mission | approval-aware |
| left leg | JOBS | long-running jobs/checkpoints | read |
| right leg | STATUS | health/evidence/runtime state | read |
| abort control | STOP | cancel current bounded operation | safe control |

Every hotspot must bind to an actual backend endpoint/capability discovery result. If a capability is unavailable, UI must display `Unavailable` or `Not connected`; it must not simulate success.

## Trail Mix adapter contract
TARS should expose a provider-neutral music/radio tool namespace. Initial methods:

- `trailmix.health()`
- `trailmix.station.list()`
- `trailmix.station.status(station_id)`
- `trailmix.now_playing(station_id)`
- `trailmix.playlist.list(station_id)`
- `trailmix.queue.read(station_id)`
- `trailmix.schedule.read(station_id)`
- `trailmix.queue.update(...)` — write/approval gated
- `trailmix.playlist.update(...)` — write/approval gated
- `trailmix.schedule.update(...)` — write/approval gated

Do not guess AzuraCast endpoint names. Implementation must inspect the current Trail Mix/AzuraCast API contracts and map adapters to verified routes.

Music generation remains a separate provider adapter (`music.generate`, `music.extend`, `music.remix`) so Suno or any future service can be swapped without changing TARS identity or Trail Mix core.

## Proof slice
First accepted proof is read-only:

1. TARS receives a mission: "Tell me what Trail Mix is playing and what is next."
2. Hermes/PAULIS-PLACE creates canonical mission/task state.
3. TARS calls the Trail Mix adapter.
4. Real station data is returned.
5. Runtime/tool/checkpoint/evidence records are written.
6. An independent verifier confirms the values against the Trail Mix API.
7. Public/3D observer receives only a sanitized event.

No fake station data may satisfy this acceptance test.
