---
name: Nonprofit Digital Trust Audit
slug: nonprofit-digital-trust-audit
description: Verify whether a nonprofit looks credible, current, findable, and internally consistent to a funder, partner, donor, or participant.
category: Impact
requires: [dish, cabinet, workbench]
license: MIT
default: false
---

Use this after or alongside `client-presence-audit` when the organization needs funder-grade public credibility rather than a general marketing review.

## Workflow

1. Inspect the official website, search results, Search Console/indexing evidence when available, LinkedIn organization presence, Google presence, public directories, donation path, contact routes, and major social accounts.
2. Capture the exact public claims a reasonable funder would encounter: organization name, legal/fiscal status, geography, programs, leadership, impact, current activity, donation destination, and contact information.
3. Mark each claim `verified`, `supported-but-incomplete`, `contradictory`, `stale`, `missing`, or `blocked` and attach source evidence.
4. Test the website as a visitor: mobile navigation, major calls to action, donation flow, mentor/volunteer/partner intake, broken links, accessibility blockers, metadata, indexing, and obvious trust gaps.
5. Compare against 1–2 relevant peer organizations only to identify missing trust signals; do not copy their claims or visual system.
6. Rank fixes by credibility impact and effort. Separate quick wins from structural work.
7. Agents may execute reversible digital fixes directly when authorized. Use a branch/PR for website code. Account creation, identity verification, legal representations, public posting, or irreversible changes require the appropriate approval gate.
8. Re-run monthly and diff only the tracked trust metrics and previously identified gaps.

## Output

- funder-view trust scorecard
- contradiction register
- quick-win queue
- technical/site issue queue
- platform/account queue
- evidence links and timestamps
- human Task Briefs only where required

## Definition of done

A third party can identify who the organization is, what it does, where it operates, how to contact/support it, and which claims are verified without encountering unresolved high-severity contradictions or broken primary paths.
