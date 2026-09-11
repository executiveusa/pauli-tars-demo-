# Software Factory release gate (Open Code Review integration)

Every candidate build in the Software Factory (BARS/TARS included) passes TWO
independent gates before anything ships. The builder never self-approves.

1. **Open Code Review flow** (repository-defined, from
   `executiveusa/open-code-review` reusable workflow @ 082d72db1398adde532832fa80392b60d074fcf2 (internal action pinned @ 22af4cb62c97959276055f3b3d977d7aa993adef),
   installed via its own `scripts/install-vibe-review.mjs`):
   - Agent skill `vibe-project-review` (`.agents/`, `.claude/`, `.codex/`,
     `.cursor/`, `.github/skills/`): review contract = MODE / OUTCOME / TARGET /
     CONSTRAINTS / PROOF / COMMERCIAL VALUE; scope = workspace | branch |
     commit | full scan; repository-native checks run as declared; verdicts:
     PASS, PASS WITH DISPOSITIONS, BLOCKED, NOT RUN.
   - Managed `VIBE_REVIEW` block in `AGENTS.md` (markers VIBE_REVIEW:START/END).
   - Independent CI: `.github/workflows/vibe-code-review.yml` calls the central
     reusable workflow `executiveusa/open-code-review/.github/workflows/vibe-code-review.yml@082d72db1398adde532832fa80392b60d074fcf2` (SHA-pinned, never a floating branch). The pin is two levels deep: at 082d72d the reusable workflow's internal action call is itself pinned to `executiveusa/open-code-review@22af4cb62c97959276055f3b3d977d7aa993adef`, whose action content is byte-identical to what the floating `@main` resolved to at pin time, so behavior is unchanged and frozen. Third-party actions used by other upstream workflows (actions/checkout@v4 etc.) are outside the called review path and remain an INFO residual, not a full supply-chain pin of the whole upstream repo.
     on every non-draft PR. Policy in `.opencodereview/rule.json` (correctness,
     security, data loss, secret exposure, rollback, tests-proving-behavior;
     "Do not approve a builder's own work").
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
