# Software Factory release gate (Open Code Review integration)

Every candidate build in the Software Factory (BARS/TARS included) passes TWO
independent gates before anything ships. The builder never self-approves.

1. **Open Code Review flow** (repository-defined, from
   `executiveusa/open-code-review` reusable workflow @ 2fab76c0695d83d3ddb71be8ae4bc7e498a9137c (internal action remains integrity-pinned by that reviewed reusable workflow),
   installed via its own `scripts/install-vibe-review.mjs`):
   - Agent skill `vibe-project-review` (`.agents/`, `.claude/`, `.codex/`,
     `.cursor/`, `.github/skills/`): review contract = MODE / OUTCOME / TARGET /
     CONSTRAINTS / PROOF / COMMERCIAL VALUE; scope = workspace | branch |
     commit | full scan; repository-native checks run as declared; verdicts:
     PASS, PASS WITH DISPOSITIONS, BLOCKED, NOT RUN.
   - Managed `VIBE_REVIEW` block in `AGENTS.md` (markers VIBE_REVIEW:START/END).
   - Independent CI: `.github/workflows/vibe-code-review.yml` calls the central
reusable workflow `executiveusa/open-code-review/.github/workflows/vibe-code-review.yml@2fab76c0695d83d3ddb71be8ae4bc7e498a9137c` (SHA-pinned, never a floating branch). The current pin is the reviewed timeout-hardened revision used by this repository. Candidate code cannot change the centrally pinned review policy because the reusable workflow is referenced by immutable commit SHA.
     on every non-draft PR.
2. **Independent security review** (parent-owned reviewer): the reviewer is
   never the builder. SHIP requires both gates green; anything else is HOLD.

## Verdict mapping (repository semantics -> release path)

- OCR critical/high unresolved (security, data-loss, authz, payment,
  deployment, rollback) -> HOLD. No merge, no deploy.
- OCR medium/low -> HOLD unless the PR records reason + owner + follow-up
  disposition per finding (PASS WITH DISPOSITIONS).
- OCR PASS + independent security review PASS -> SHIP candidate only. Merge
  still requires the independent human/governed reviewer; deploy still
  requires the production verification and rollback evidence already in
  DEPLOY.md.
- OCR BLOCKED or NOT RUN -> HOLD with the exact blocker recorded.

## Required release evidence (per candidate)

- OCR workflow run URL + summary; reviewed base/head commits; finding
  dispositions (critical/high/medium/low); native check outcomes
  (`tests/run_all.sh` ledger counts); independent security review verdict;
  production verification evidence when production is claimed; rollback
  method; exact human approval still required.

All pre-existing gates are preserved and unchanged: money/paid-call gates,
publishing and external-message gates, destructive-operation gates,
production/cutover freezes. This gate ADDS independence; it loosens nothing.
