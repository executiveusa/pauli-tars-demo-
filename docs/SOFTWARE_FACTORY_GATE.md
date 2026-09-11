# Software Factory release gate (Open Code Review integration)

Every candidate build in the Software Factory (BARS/TARS included) passes TWO
independent gates before anything ships. The builder never self-approves.

1. **Open Code Review flow** (repository-defined, from
   `executiveusa/open-code-review` reusable workflow @ 864933213372cc488b3f2f2b1deaab84ea91b855 (internal action pinned @ 2d685ab0d057aec8255f18cd0a5f5a14fbfd5195; immutable execution: scripts-disabled install, independently verified binary, updater disabled, centrally pinned policy),
   installed via its own `scripts/install-vibe-review.mjs`):
   - Agent skill `vibe-project-review` (`.agents/`, `.claude/`, `.codex/`,
     `.cursor/`, `.github/skills/`): review contract = MODE / OUTCOME / TARGET /
     CONSTRAINTS / PROOF / COMMERCIAL VALUE; scope = workspace | branch |
     commit | full scan; repository-native checks run as declared; verdicts:
     PASS, PASS WITH DISPOSITIONS, BLOCKED, NOT RUN.
   - Managed `VIBE_REVIEW` block in `AGENTS.md` (markers VIBE_REVIEW:START/END).
   - Independent CI: `.github/workflows/vibe-code-review.yml` calls the central
reusable workflow `executiveusa/open-code-review/.github/workflows/vibe-code-review.yml@864933213372cc488b3f2f2b1deaab84ea91b855` (SHA-pinned, never a floating branch). Executed code is pinned and integrity-locked end to end, and NO mutable code runs: the caller pins the reusable workflow @ 8649332; its internal action call is pinned to `executiveusa/open-code-review@2d685ab0d057aec8255f18cd0a5f5a14fbfd5195`; that action (a) installs ONLY `@alibaba-group/open-code-review@1.11.8` from an npm tarball verified against a recorded sha512 (`DhFkYIhCx+omtbMKY4bTpJLaZtfn6kHZlxmZyCYMOxDcimp3R3BOWwnXNy/m8kzqwviX74sVprG7sS1j7f8swQ==`), with `--ignore-scripts` so NO package lifecycle script executes; (b) downloads the native binary itself and verifies sha256 (linux/amd64 `d6654cc065c1e844f32e15290bcdb2fe1b7c5d5d6f46e6484987985bc5300f77`, linux/arm64 `ccc206fcb2be26a177ee665d4b768188232108b5bed978a58c5ac988ae00143e`) before placing it, independent of the package's own postinstall; (c) sets `OCR_NO_UPDATE=1` before every `ocr` invocation because the launcher's updater (scripts/update.js, spawned by bin/ocr.js when unset) can install npm @latest while inheriting OCR_LLM_TOKEN; and (d) SHA-pins every nested action in the called path (setup-node@49933ea5, checkout@11d5960a, upload-artifact@ea165f8d, github-script@f28e40c7 - full SHAs in the pinned files). Any unknown version or hash mismatch fails closed. TRUSTED POLICY SOURCE: the review policy is the centrally pinned policy shipped INSIDE the pinned action at `policy/rule.json`; when the caller leaves `rule` empty (this repo's caller does) the action passes that file to `ocr review --rule` and logs the source. A candidate-checked-out `.opencodereview/rule.json` NEVER governs CI review - the candidate cannot control its own judge; such a file is forbidden in this repo by scripts/check_release_gate.py. Actual residuals (named, not hidden): the GitHub-hosted runner image, GitHub Actions itself, the npm registry and GitHub Releases availability at run time, third-party actions in OTHER upstream workflows outside the called path (INFO residual), and the OPENROUTER_API_KEY secret value itself (repo secret, never printed). A mandatory OCR CI run on the exact final candidate is still required after Bambu approves PR creation and the secret is funded; until then the in-tree independent review remains the binding gate and no claim is made that OCR CI has passed.
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
