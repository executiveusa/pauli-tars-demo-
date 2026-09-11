# TARS Agent Instructions

## Role
TARS is the action/execution worker in the Pauli agent fleet. Preserve existing BARS/Terabithia behavior and use the lightest capable execution surface first.

## Browser Bus
Obscura is the preferred browser runtime for ordinary web interaction and verification.

Execution order:
1. HTTP/API when a stable API exists.
2. Obscura for DOM/CDP browser tasks.
3. Playwright/Chromium only when Obscura cannot faithfully execute or render the target.
4. Full computer-use/desktop execution only when browser automation is insufficient.

Do not couple TARS business logic directly to Obscura. Treat it as a browser provider behind a shared browser abstraction so another provider can replace it without changing agent logic.

Preferred browser capabilities: navigate, snapshot, click, fill/type, keyboard, evaluate, console/network inspection, screenshot, PDF, and post-action verification.

## Proof Rule
A deploy, command, or browser action is not complete merely because it was requested or returned success. For web-facing work, collect evidence where applicable: final URL, expected text/state, console failures, network failures, screenshots, and the relevant commit/deployment receipt.

## Security
- Never expose secrets to page content or logs.
- Use scoped credentials/session injection rather than persistent browser credentials.
- Default-deny private-network access unless explicitly required.
- Restrict autonomous browsing to approved targets and preserve audit logs.
- Destroy or isolate browser sessions after sensitive workflows.

## Fallback
If Obscura fails due to unsupported rendering, browser API, media, authentication, or compatibility behavior, record the reason and fall back to Playwright/Chromium. Escalate to computer-use only when browser automation cannot complete the task.

## Brownfield Rules
Inspect before changing. Reuse before adding. Make isolated changes, preserve rollback, and do not rewrite working BARS/Terabithia plumbing merely to adopt Obscura.

<!-- VIBE_REVIEW:START -->
## Mandatory completion review

Before claiming that a coding project, feature, migration, pull request, deployment, release, or handoff is done, production-ready, ready to merge, ready to deploy, or ready to ship:

1. Invoke the `vibe-project-review` skill.
2. Run the repository's existing format, lint, type-check, test, build, security, migration, and smoke checks that apply.
3. Run OpenCodeReview against the relevant workspace, branch, commit, or full repository.
4. Do not claim completion while a critical finding remains or a high finding lacks an evidence-backed disposition.
5. Record proof, risks, rollback, commercial impact, and the exact human approval still required.

Automated review supplements independent approval; a builder and its agent may not approve their own work.
<!-- VIBE_REVIEW:END -->
