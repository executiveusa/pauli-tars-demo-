---
name: Nonprofit Funding Readiness
slug: nonprofit-funding-readiness
description: Turn a nonprofit or social-purpose organization into an evidence-backed funding-readiness dossier and prioritized execution backlog.
category: Impact
requires: [dish, cabinet, workbench]
license: MIT
default: false
---

Use this before grant writing, donor outreach, sponsorship asks, or financing research. The purpose is to determine whether the organization is ready to be evaluated by a funder and to convert gaps into owned StarNet missions.

## Inputs

- organization name, website, geography, mission, program stage
- entity/fiscal-sponsor status as actually documented
- current fundraising channels and known funding history
- available governance, finance, impact, program, and contact records

## Workflow

1. Establish the organization truth set. Separate verified facts, operator claims, assumptions, unknowns, and blocked evidence.
2. Audit the minimum funder-facing package: legal/entity status, fiscal sponsorship where applicable, mission/program description, leadership/governance, current budget and financial controls, measurable outcomes, contact information, website/donation paths, and required supporting documents.
3. Run `client-presence-audit` for the public-facing baseline. Do not duplicate its collection work.
4. Check for contradictory names, addresses, descriptions, status claims, donation destinations, program claims, or contact information across public surfaces.
5. Produce a readiness scorecard using `verified`, `partial`, `missing`, `blocked`, and `not-applicable`; never infer completion from a draft.
6. Rank gaps by funding impact, effort, dependency, legal/financial risk, and time sensitivity.
7. Convert the top gaps into StarNet missions with an owner, next action, evidence requirement, approval rule, due date, and definition of done.
8. Produce a funding-readiness dossier and 30/60/90-day action plan.

## Human approval gates

Require a Task Brief before legal attestations, signatures, tax/entity claims, bank or credit applications, financial commitments, final grant certifications, or public claims that materially affect the organization.

## Evidence contract

Completion requires source URLs or source files, retrieval date, verification status, and an artifact/action receipt. If the evidence cannot be obtained, mark the item blocked or unknown.

## Definition of done

The organization has a traceable readiness dossier, prioritized backlog, clear human-only decisions, and no unresolved high-impact contradiction hidden behind a numeric score.
