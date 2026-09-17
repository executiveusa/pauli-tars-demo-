---
name: loop-engineering
description: ICM-based zero-to-verified engineering workflow. Use when asked to take a product, repo, website, agent, workflow, or digital system from idea or current state through discovery, architecture, task graph, specification, bounded implementation, independent verification, gauntlet comparison, release, rollback, and learning. Routes only the skills needed for the current stage. Requires a real quality bar before substantial work.
---

# Loop Engineering

One skill. Small context. Full lifecycle.

This file is a router, not the playbook. Do not load the whole workspace.

## Start

1. Read `AGENTS.md`.
2. Read root `CONTEXT.md` when present.
3. Determine `MODE`: greenfield or brownfield.
4. Inspect before asking questions when a repo/product already exists.
5. Establish a **BAR** before substantial work. If the user did not name one, propose specific, fetchable, comparable bars.
6. Create or resume one durable run packet.
7. Follow the next stage recorded in that run.

## Core operating law

`INTENT -> BAR -> LOCK -> EVIDENCE -> GRAPH -> SPEC -> SLICE -> BUILD -> VERIFY -> GAUNTLET -> RELEASE -> LEARN`

The outer loop repeats only when evidence says the current result has not cleared the bar. The task graph exists inside the loop and parallelizes only genuinely independent work.

## Never

- claim completion from code presence, CI, or deployment alone;
- let a builder approve its own work;
- start a rewrite before brownfield inspection;
- run every skill on every task;
- add a framework because it is interesting;
- expose secrets or move owner authority into the browser;
- ship without rollback and production evidence;
- create more active work merely because agents are available.

## BARS operating interpretation

BARS is brownfield unless explicitly creating a new product. BARS uses Hermes as the execution engine and this skill as the engineering governor.

For artist/media work, use the same lifecycle. A creative render is not a release. A release must prove asset provenance, tool/provider receipts, target delivery, rollback/re-render path, and any human approval required for publishing/spend/account mutation.

## End-state words

Use only: `NOT READY`, `READY FOR PREVIEW`, `PREVIEW VERIFIED`, `PRODUCTION VERIFIED`.

`PRODUCTION VERIFIED` requires runtime evidence from the exact released revision.
