---
name: Client Presence Audit
slug: client-presence-audit
description: Audit a client's public web/social/local presence into a scored gap report and phased growth strategy, weighted by client type (SMB / social-purpose / nonprofit).
category: Marketing
requires: [dish, cabinet, workbench]
license: MIT
default: false
---

Turn a business name into a structured audit report: what their public
presence actually shows today, what's missing, and a phased plan to fix
it — the Revenue district's audit-to-capture pattern applied to client
work. For the raw collection method (schema-first, source-traced rows),
see Dataset Harvest — this skill is the audit-specific layer on top of
it: what to collect, how to weight it per client type, and what shape
the output takes.

Use for: prospecting a new agency client, running a baseline before
starting work, or a monthly re-run to show progress against that
baseline. Do NOT use for general competitor research (use Marketing
Plan) or for a one-off "how does site X look" (that's plain web_fetch).

## Method

1. **Confirm the client type before anything else.** `smb`,
   `social-purpose`, or `nonprofit` — this changes what you weight in
   step 3 and how you frame the strategy in step 5. Never assume; ask if
   unstated.

2. **Collect, schema-first (Dataset Harvest method applies).** Sources:
   client's own website, Google Search/Maps/GBP, Yelp, Instagram,
   YouTube, and 1–2 comparable competitors on the same fields. Fetch
   through bound connector portals where the source is bot-protected
   (Google, Yelp, Instagram at volume need a connector-exchange-bound
   unblocking connector — plain `web_fetch` will get rate-limited or
   blocked on these). Every row traces to the page it came from and the
   timestamp fetched.

3. **Weight by client type:**
   - `smb` — local search + reviews heaviest (GBP, Yelp, local-pack
     ranking for brand + service + location terms).
   - `social-purpose` — commercial presence AND whether the impact
     narrative is visible where a buyer/supporter would look (About
     page, bios, press).
   - `nonprofit` — donor/volunteer funnel visibility, GBP (donors search
     "[cause] near me"), a findable donate/volunteer path.

4. **Never fabricate a blocked field.** If a source can't be collected
   after a real attempt, the row says so explicitly — a confident guess
   here is worse than an honest gap, because the report becomes the
   thing the Commander sells work against.

5. **Report shape, in this order:** Executive Summary (3–5 bullets) →
   Current State Snapshot (metrics table, confidence-flagged) →
   Competitive Context → Gaps & Opportunities (ranked impact vs. effort,
   stated as falsifiable problems, not vague advice) → Recommended
   Strategy (30/60/90 days, phased per the client-type emphasis above) →
   Metrics to Track Going Forward (the exact numbers a monthly re-run of
   this skill will compare against).

6. **On re-run (monthly progress check):** diff this run's collection
   against the first run's baseline and the prior month's report on the
   named tracked metrics only — this is a change-over-time report, not a
   fresh audit.
