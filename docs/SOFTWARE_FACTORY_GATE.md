# Software Factory release gate (Open Code Review integration)

Every candidate build in the Software Factory (BARS/TARS included) passes TWO
independent gates before anything ships. The builder never self-approves.

1. **Open Code Review flow** (repository-defined, from
   `executiveusa/open-code-review` reusable workflow @ ca8d7a87f30b556a3f898e59d6993f076852a188 (internal action pinned @ 079c7c28b2e10e47ff1ddd8df8f5138ea2efff79, executed package integrity-locked),
   installed via its own `scripts/install-vibe-review.mjs`):
   - Agent skill `vibe-project-review` (`.agents/`, `.claude/`, `.codex/`,
     `.cursor/`, `.github/skills/`): review contract = MODE / OUTCOME / TARGET /
     CONSTRAINTS / PROOF / COMMERCIAL VALUE; scope = workspace | branch |
     commit | full scan; repository-native checks run as declared; verdicts:
     PASS, PASS WITH DISPOSITIONS, BLOCKED, NOT RUN.
   - Managed `VIBE_REVIEW` block in `AGENTS.md` (markers VIBE_REVIEW:START/END).
   - Independent CI: `.github/workflows/vibe-code-review.yml` calls the central
reusable workflow `executiveusa/open-code-review/.github/workflows/vibe-code-review.yml@ca8d7a87f30b556a3f898e59d6993f076852a188` (SHA-pinned, never a floating branch). The executed code is pinned and integrity-locked end to end: the caller pins the reusable workflow @ ca8d7a8; at ca8d7a8 the internal action call is pinned to `executiveusa/open-code-review@079c7c28b2e10e47ff1ddd8df8f5138ea2efff79`; that action installs ONLY `@alibaba-group/open-code-review@1.11.8` after verifying the npm tarball sha512 (`DhFkYIhCx+omtbMKY4bTpJLaZtfn6kHZlxmZyCYMOxDcimp3R3BOWwnXNy/m8kzqwviX74sVprG7sS1j7f8swQ==`) and the postinstall native binary sha256 (linux/amd64 `d6654cc065c1e844f32e15290bcdb2fe1b7c5d5d6f46e6484987985bc5300f77`, linux/arm64 `ccc206fcb2be26a177ee665d4b768188232108b5bed978a58c5ac988ae00143e`) against constants recorded in the pinned action itself - any other version or a hash mismatch fails closed. The exact version is exposed as `ocr_version` through both workflows (default 1.11.8; the caller passes it explicitly). The npm package and native binary were inspected as untrusted content before pinning (thin launcher + postinstall downloader; zero runtime dependencies). Honest residual: this is NOT a full supply-chain pin of the universe - the GitHub runner image, GitHub Actions itself, and third-party actions in OTHER upstream workflows (outside the called review path) remain outside the pin (INFO residual). Workflow permissions are the least required for the documented behavior: contents:read (diff), pull-requests:write (inline comments), issues:write (sticky summary via the issues API); no contents:write.
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
