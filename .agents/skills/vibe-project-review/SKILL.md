---
name: vibe-project-review
description: Mandatory completion and release review gate for Vibe Engineering projects. Use automatically whenever an agent is about to claim that a coding project, feature, migration, rescue sprint, pull request, deployment, release, or handoff is finished, done, production-ready, ready to merge, ready to deploy, ready to ship, or ready for approval. Also use when asked to review and fix a repository before completion. Runs project-native checks and OpenCodeReview, resolves or records findings, verifies rollback and evidence, and prevents unsupported completion claims.
---

# Vibe Project Review

Treat this skill as a mandatory completion gate, not an optional quality pass.

The builder may repair findings, but must not approve its own work. A successful automated review is evidence for an independent human or separately governed reviewer; it is not permission to merge or deploy.

## 1. Establish the review contract

Before reviewing, derive and state:

- **MODE:** greenfield or brownfield.
- **OUTCOME:** the measurable result requested.
- **TARGET:** customer, user, system, repository, branch, or release.
- **CONSTRAINTS:** what must not change.
- **PROOF:** evidence required to support completion.
- **COMMERCIAL VALUE:** revenue, savings, retention, delivery, or validated learning.

Do not broaden scope merely because unrelated defects exist. Record unrelated findings separately.

## 2. Determine the review scope

Inspect the repository before changing anything:

```bash
git status --short
git branch --show-current
git remote -v
git log -1 --oneline
```

Select exactly one primary review mode:

- **Workspace review:** staged, unstaged, and untracked implementation work.
- **Branch review:** compare the working branch with the repository default branch or agreed base.
- **Commit review:** inspect a specific commit.
- **Full scan:** required before first production-ready classification and after material architecture, authentication, authorization, payments, database, infrastructure, dependency, secret-handling, or external-side-effect changes.

Skip only when the entire change is non-executable prose or media and cannot alter runtime, configuration, infrastructure, security, data, or deployment behavior. Record the reason for the skip.

## 3. Run repository-native checks

Inspect existing manifests and automation. Reuse declared commands; do not invent a new toolchain during review.

Run all applicable existing checks, typically:

1. formatting or formatting verification;
2. lint;
3. static analysis or type checking;
4. unit and integration tests;
5. build or compile;
6. repository-specific security, migration, smoke, or deployment checks.

Do not hide failures with `|| true`, reduced test scopes, disabled rules, or altered configuration. If a check cannot run, report the exact blocker and mark proof incomplete.

Never print, copy, or commit secrets. Redact credentials from evidence.

## 4. Run OpenCodeReview

Verify the CLI:

```bash
which ocr
ocr --version
```

Install it only when installation is allowed and necessary:

```bash
npm install -g @alibaba-group/open-code-review
```

Build concise business background from the review contract, architecture, risk, and changed behavior.

### OCR-managed mode

When `ocr llm test` succeeds, run the applicable command with agent output:

```bash
ocr llm test
ocr review --audience agent --background "<business and risk context>"
ocr review --audience agent --background "<business and risk context>" --from <base> --to HEAD
ocr review --audience agent --background "<business and risk context>" --commit <sha>
ocr scan --background "<business and risk context>"
```

Use `.opencodereview/rule.json` automatically when present. Never hardcode credentials.

### Delegation fallback

When no OCR LLM is configured, use delegation mode for the local agent review:

```bash
ocr delegate preview
ocr delegate rule <selected-files>
```

Review every selected file against the resolved OCR rules. State that delegation is a local preflight, not an independent reviewer. The GitHub Actions review must still run before merge or release.

## 5. Classify and disposition findings

Classify each supported finding:

- **Critical:** exploitable security failure, credential exposure, destructive data loss, authorization bypass, payment corruption, irreversible migration, or production-control loss.
- **High:** clear correctness, security, reliability, deployment, rollback, or external-side-effect defect.
- **Medium:** credible maintainability, performance, test, resilience, or edge-case concern.
- **Low:** style, documentation, speculative concern, or probable false positive.

For each finding, choose one disposition:

- fixed and verified;
- accepted with reason, owner, and follow-up;
- false positive with evidence;
- blocked pending human decision.

Do not silently discard findings.

## 6. Repair and rerun

When repair is within the authorized scope:

1. Make the smallest isolated fix.
2. Rerun the affected native checks.
3. Rerun OpenCodeReview against the updated diff.
4. Confirm that the fix did not expand the blast radius.

Stop the completion claim when any critical finding remains, or when a high finding lacks an explicit evidence-backed disposition.

## 7. Verify completion separately from deployment

A passing build, review, CI run, or deployment request does not prove production.

Before describing a release as production-verified, require evidence of:

- successful target-environment deployment;
- expected route or service behavior;
- database and migration health when applicable;
- relevant logs or monitoring without unresolved critical errors;
- ownership of code, domain, hosting, database, credentials, and data;
- a documented and feasible rollback.

## 8. Return the completion record

Use one status only:

- **PASS:** checks passed and no unresolved critical or high findings remain.
- **PASS WITH DISPOSITIONS:** checks passed; accepted medium or low findings are documented.
- **BLOCKED:** a required check failed, evidence is missing, or a critical/high finding remains.
- **NOT RUN:** review could not execute; never represent this as completion.

Return:

```markdown
## DECISION
## CHANGES
## PROOF
## STATUS
## COMMERCIAL IMPACT
## RISKS
## ROLLBACK
## NEXT
## HUMAN APPROVAL
```

Under **PROOF**, include commands and outcomes, OCR mode and scope, reviewed base/head or scan paths, findings and dispositions, and deployment verification evidence when claimed.

Under **HUMAN APPROVAL**, state the exact approval still required. Never auto-merge, auto-deploy, or declare production solely because this skill passed.