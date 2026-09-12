---
name: Niche Scraper Productization
slug: niche-scraper-productization
description: Find an underserved scraping niche, build an Apify Actor for it, and publish it on Apify Store under pay-per-event pricing — turning scraping capability into a standing revenue line instead of only internal tooling.
category: Research
requires: [dish, cabinet, workbench]
license: MIT
default: false
---

Most of what this station scrapes for its own audits (Client Presence
Audit, Dataset Harvest, etc.) is internal cost. This skill flips that:
find a scraping job enough *other* people need that they'd pay per
result for it, build it once as an Apify Actor, and let it earn on
autopilot after that — compounding revenue instead of a one-off
deliverable.

Use for: a standing, repeatable cycle — run it again once an Actor is
live and earning, to find the next niche. Do NOT use for building a
scraper that's only for this station's own audits (that's Dataset
Harvest); this skill is specifically for something built to be sold.

## Method

1. **Find the niche — evidence, not a guess.** Search Apify Store by
   category. Look for: existing Actors with high run counts but bad
   reviews (a proven-demand market with a quality gap), a specific site
   or data type with no Actor at all but visible demand elsewhere
   (Reddit r/webscraping, Apify's own Discord requests, "how do I scrape
   X" search volume), or an Actor that's stale (no updates in 6+ months,
   breaking-change complaints in reviews). A niche with existing paid
   Actors, even bad ones, is stronger evidence than an empty category —
   it proves people already pay for this.

2. **Validate before building anything.** For the top 2–3 candidates: is
   the target site's blocking difficulty something native `web_fetch` +
   the Apify connector can actually solve reliably, or does it need
   capabilities this station doesn't have? Is there a disqualifying ToS/
   legal exposure for this specific target (flag it, don't build it)? Is
   the data genuinely valuable structured (has fields worth $ per row)
   or just page text someone could `web_fetch` themselves for free — the
   latter won't sell.

3. **Build the Actor**, Apify's standard shape: `Dockerfile`,
   `actor.json`, `INPUT_SCHEMA.json`, `main.js`/`main.py`, `README.md`
   with a clear description and example use cases (Apify Store
   discovery depends on this being genuinely readable, not
   boilerplate). Output a clean, consistently-shaped dataset row per
   item — that row IS the product.

4. **Test against the real target before publishing.** Run it enough
   times to see it survive the site's actual anti-bot behavior, not
   just a happy-path single run. If it breaks under repeated use,
   that's a pricing-and-reliability problem to fix now, not a
   launch-day surprise.

5. **Price it pay-per-event, not rental.** Rental listings are being
   phased out — don't build toward a model Apify is retiring. Define
   the event (one result row, one profile, one page) and price it
   against what the validated demand in step 1 already showed people
   pay for comparable Actors.

6. **Publish, then log it.** Store the Actor's Store URL, its niche
   evidence, and its pricing rationale in `notebook.write` — this is
   the record the next run of this skill checks so it doesn't
   rediscover or duplicate a niche already covered.

7. **Report to the Commander:** the niche, the evidence it was real
   (not assumed), the live Store listing, and one honest read on risk
   (reliance on a specific site not changing its layout, any ToS
   exposure accepted knowingly). Never claim expected revenue — that's
   Apify's own Actor Insights dashboard to check after it's live, not
   something to project.
