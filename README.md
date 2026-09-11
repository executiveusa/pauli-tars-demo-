# BARS — Culture DJ + Mission Operator

**BARS is the artist-facing operator for Trail Mixx and a bounded execution agent in the Pauli fleet.**

BARS combines a 3D interactive character, voice/chat, background missions, computer-use controls, media/music workflows, and Trail Mixx radio operations behind one simple front door.

> Jarvis is the presence layer. Hermes orchestrates the business. BARS operates the music/media/computer domain.

## What BARS does

- **Talk + type** — natural chat, voice input, and full-duplex live conversation.
- **Run bounded missions** — deploy named workers for research/build tasks and report back with evidence.
- **Computer use** — see the screen and, after explicit permission, control the mouse/keyboard with an emergency stop.
- **3D interface** — the browser character is the primary product surface and will expose touch-friendly body controls.
- **Trail Mixx** — BARS is the operator for the Trail Mixx radio/music experience. The station backend stays a separate system and BARS talks to it through a governed adapter rather than absorbing the whole radio codebase.
- **Music/media adapters** — generation, remix, queue, scheduling, publishing, and analysis are provider-agnostic so the product is not locked to one vendor.

## Cross-platform

| Feature | macOS | Windows | Linux |
|---|---:|---:|---:|
| Chat + voice + missions | Yes | Yes | Yes |
| 3D character in browser | Yes | Yes | Yes |
| Jobs board (CASE/KIPP/PLEX) | Yes | Yes | Yes |
| Floating desktop character | Yes (pyobjc) | Yes (PyQt6) | Yes (PyQt6) |
| Screen takeover | Yes (Quartz) | Yes (pyautogui) | Limited |
| Hue smart lights | Yes | Yes | Yes |

## Requirements

| What | Why | Required? |
|---|---|---:|
| **Python 3.10+** | Runs the local/server runtime | Yes |
| **Groq API token or OpenRouter-compatible route** | Conversational/reasoning brain (free-first routing; paid escalation off unless explicitly enabled) | Yes for current runtime |
| **Claude Code CLI** (`claude`) | Powers some background missions | Recommended |
| OpenAI API key | Live voice + dictation | Optional |
| ElevenLabs API key | Premium voice | Optional |

### Windows extras

```bash
pip install pyautogui mss Pillow PyQt6
```

### macOS extras

```bash
pip install pyobjc-core pyobjc-framework-Quartz
```

## Install

### Windows

1. Put the repo in a folder such as `C:\BARS`.
2. Copy `config.example.json` to `config.json` and add the provider keys you intend to use.
3. Double-click `start-bars.bat`.
4. Open `http://localhost:4321` if the browser does not open automatically.

### macOS

1. Put the repo in a folder such as `~/BARS`.
2. Copy `config.example.json` to `config.json` and add the provider keys you intend to use.
3. Double-click `Launch BARS.command`.
4. Grant microphone/screen permissions only when you choose to use those features.

## 10-second tour

- Say or type: **“BARS, show me what you can do.”**
- Give a mission: **“Send CASE to research X.”**
- Ask to see the screen: **“BARS, look at my screen.”**
- Computer takeover always asks permission before driving the real mouse/keyboard.
- Trail Mixx controls will appear as a dedicated body/touch surface once the adapter is connected and verified.

## Safety and trust model

BARS is draft-safe by default. Outward actions such as sending, posting, publishing, pushing code, spending money, or taking over the computer require the appropriate confirmation boundary. The red stop/abort control must remain available during computer-use actions.

- **Fail-closed operator auth.** Every API call needs the `BARS_OPERATOR_TOKEN` bearer token. The server refuses to start without it (`BARS_OPEN_LOCAL=1` exists for local development only).
- **Single-use confirmations.** Sensitive actions mint a short-lived confirmation that binds the exact action, a hash of the exact payload, the target, and a displayed worst-case token bound. The executing endpoint re-hashes what it was asked to run, so nothing can be swapped between review and execution. Confirmations are bound to the principal that minted them and burn on use.
- **Displayed bound = enforced bound.** The token bound shown at approval time is registered as an aggregate cap on the mission and enforced with atomic reservations; a call that would exceed it fails closed. This holds for `/brief`, `/act`, squads (split and children share one bound), and follow-up missions.
- **Free-first routing, paid fail-closed.** The default model lane is a free provider. Paid escalation stays off unless explicitly enabled, and every paid or voice call is confirmation-gated with an atomic budget hold.
- **Truthful aborts.** Aborting a mission always reaches a persisted terminal state (ABORTED), whether the abort lands before, during, or after a model call, and a dead mission's cost cap is released. A squad child can never release the shared parent cap.
- **Isolated internal worker.** On hosts without the coding CLI, missions run in a provider-only worker with no shell, no file writes outside the mission report, and no external tools.

Never commit production secrets. `config.json` and generated local tokens/state are local runtime data.

## Sovereign deployment

The authoritative BARS agent runs as an exact-SHA Docker deployment behind Caddy on the VPS (see `DEPLOY.md`). The Netlify site stays a static visual reference only; it is not a backend.

- **Immutable identity.** Images are tagged with the full 40-character git SHA and carry that SHA baked in at build time. `/health` reports the exact running SHA, and deploys and rollbacks verify it before going live. No mutable tags, no env-echo identity.
- **Reversible deploys.** `deploy/rollback.sh` restores the previous exact image only after health verifies the restored SHA, and `--with-data` restores the deployment-linked data snapshot (taken through a root helper when the host user cannot read container-written state). Deploy bookkeeping is intentionally non-transactional: rollback is the transaction.
- **Durable state.** Missions, receipts, dials, and configuration live on a host volume (`/opt/bars/data`), never in the image.

## Verification and release gate

- **Test ledger.** 245 behavioral assertions across versioned adversarial suites in `tests/`, runnable locally with `tests/run_all.sh`. Suites prove behavior (live server, mock provider, real Docker), not source-string presence.
- **Real-Docker CI.** Every push runs the deploy/rollback suite on an ephemeral GitHub-hosted runner with no repo secrets (`.github/workflows/docker-integration.yml`), covering snapshot fallback on unreadable host data, failed-health rollback bookkeeping, and full data rollback. The workflow publishes sha256 hashes of the raw evidence into the public run log and check summary, and the committed receipts in `docs/evidence/` are byte-identical to the CI artifact.
- **Independent review.** SHIP requires both the repository gate and a review the builder does not control (`docs/SOFTWARE_FACTORY_GATE.md`). The CI review policy is centrally pinned inside the SHA-pinned review action; a candidate-checked-out policy file never governs review and is forbidden in this repo.
- **Current status.** The frozen candidate on `fix/bars-sovereign-runtime` passed fourteen rounds of adversarial and independent outside review. Full release remains HOLD until the PR is opened and the mandatory Open Code Review CI run passes on the exact final candidate. Nothing is merged or deployed from this branch.

## Environment variables

| Variable | Why | Required? |
|---|---|---:|
| `BARS_OPERATOR_TOKEN` | Bearer token for every API call | Yes (server refuses to start without it) |
| `BARS_OPEN_LOCAL=1` | Local development without a token | Dev only |
| `BARS_DATA_DIR` | Durable state directory | Default: repo root locally, `/data` in the container |
| `GROQ_API_TOKEN` | Free default model lane | Yes for the default brain |
| `BARS_ALLOWED_ORIGINS` | Cross-origin browser callers | Production only |

## Fleet role

The permanent Pauli fleet is:

- **Hermes / Pauli** — business orchestrator and mission delegation.
- **Pi** — private Human OS / personal second brain.
- **BARS** — computer, music, media, Trail Mixx, and bounded operator work.
- **Jarvis** — voice/phone/glasses presence layer.
- **Lightning** — independent watchdog and memory curator.

Temporary subagents/workers may be created for missions, but they are not additional permanent fleet members.

## Trail Mixx

Canonical source repo: `executiveusa/trail-mixx-source-code` (AzuraCast-based self-hosted radio stack).

BARS should integrate through a thin governed adapter with explicit read/write capabilities such as station health, now-playing, playlists, queue, and scheduling. Do not merge the entire Trail Mixx/AzuraCast codebase into BARS.

## Definition of done

A rendered page or successful HTTP response is not enough. A BARS capability is done only when a real user action reaches the real backend/tool, produces an observable result, records evidence/checkpoints where required, survives the tested failure path, and has a rollback.

Built by The Pauli Effect.
