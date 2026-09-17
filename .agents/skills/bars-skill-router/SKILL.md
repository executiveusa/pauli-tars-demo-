# BARS Lean Skill Router

## Purpose

Route BARS work through the owner-approved live skill cut without loading the archived 370-skill catalog into context.

Canonical registry: `bars/skills/live-registry.json`.

## Governing rule

A skill stays live only when BARS can say in one sentence when it should be reached for. Prefer one canonical entry point per overlapping family. Keep archived/template-specific skills out of live context unless a human explicitly asks for one.

## Routing order

1. Identify the lane: factory/judge, creative, UGC/video, 3D, voice, agency, or ops.
2. Choose the smallest canonical skill whose `reach_for` sentence matches the task.
3. If a family has collapsed modes, invoke the canonical parent skill and treat the old sibling names as modes, not separate competing skills.
4. For release-bound work, pair the builder skill with `adversarial-review-pass`, then require evidence before claiming success.
5. For pricing/selling, invoke `icm-pricing` before presenting an evidence-backed price.
6. For design work, preserve the PARÉ spine as one coherent doctrine system.

## PARÉ spine

Treat these as an atomic doctrine set:

- pare-brand-discovery
- pare-collins-level
- pare-completion-gates
- pare-design-delivery
- pare-design-guardian
- pare-design-proof
- pare-gauntlet
- pare-humanize
- pare-seo
- pare-subtraction
- pare-svg-engineering
- pare-doctrine

Do not replace PARÉ with generic design boilerplate.

## Family collapse

Use these single entry points instead of sibling roulette:

- decks -> `html-ppt`
- review -> `adversarial-review-pass`
- frontend -> `frontend-design`
- humanizer -> `pare-humanize`
- speech -> `speech`
- GSAP -> `gsap`
- Figma -> `figma`
- fal -> `fal`
- Venice -> `venice`
- Orbit -> `orbit`
- wireframes -> `wireframe`
- web prototypes -> `web-prototype`
- image generation -> `imagegen`
- design taste -> `design-taste`
- dashboards -> `dashboard`

## Installation truthfulness

The registry distinguishes routing contracts from resolved physical skill bodies. A `manifest-contract` entry means BARS has the owner-approved trigger/routing contract but MUST NOT claim that a separate external skill package is physically installed unless its source path has been resolved and copied into the Hermes runtime.

## Release behavior

For any consequential external action, deployment, publishing, spending, deletion, or account mutation, preserve existing BARS approval boundaries. Do not bypass Loop Engineering or the BARS production proof gate.
