# BARS Sovereign Deployment (Hostinger VPS)

Architecture:

```
Internet → HTTPS (Caddy on the VPS) → 127.0.0.1:4321 BARS container
                                      127.0.0.1:4323 duplex brain (never published)
                                      /opt/bars/data (durable volume)
```

The authoritative BARS agent runs on the VPS. Netlify (`barsdemo`) stays a
static visual reference/fallback only — it is not a backend.

## Prereqs (one-time, on the VPS)

1. Docker present (`docker --version`). Coolify optional — this path works
   with plain Docker; under Coolify, point it at this repo/branch and copy the
   same env + volume + port settings.
2. `sudo mkdir -p /opt/bars/data /opt/bars/backups /opt/bars/logs`
3. `/opt/bars/.env` from `.env.example` with real values from Infisical:
   - `GROQ_API_TOKEN` (Infisical HERMES, verified valid — NOT the expired
     `GROQ_API_KEY`)
   - `BARS_OPERATOR_TOKEN` = `openssl rand -hex 32` (store in Infisical as
     `BARS_OPERATOR_TOKEN`)
   - `BARS_ALLOWED_ORIGINS=https://barsdemo.netlify.app`
4. DNS: `bars.thepaulieffect.com` A record → `31.220.58.212`, DNS-only
   (grey cloud) in the Cloudflare zone `96712684919a639674c22fee58732ed9`.

## Deploy

```bash
cd /opt/bars
git clone https://github.com/executiveusa/pauli-tars-demo-.git app
cd app && git checkout <merged-main-SHA>
export BARS_GIT_SHA=$(git rev-parse --short HEAD)
docker build -t bars-sovereign:$BARS_GIT_SHA -t bars-sovereign:latest .
docker run -d --name bars --restart unless-stopped \
  --env-file /opt/bars/.env -e BARS_GIT_SHA=$BARS_GIT_SHA \
  -v /opt/bars/data:/data -p 127.0.0.1:4321:4321 \
  --memory 512m --cpus 0.75 --pids-limit 128 \
  bars-sovereign:$BARS_GIT_SHA
```

Then append `deploy/Caddyfile.bars` to the system Caddyfile and
`systemctl reload caddy`.

## Verify (smoke)

```bash
curl -s https://bars.thepaulieffect.com/health
curl -s -H "Authorization: Bearer $BARS_OPERATOR_TOKEN" \
  https://bars.thepaulieffect.com/api/status
curl -s -X POST https://bars.thepaulieffect.com/chat \
  -H "Authorization: Bearer $BARS_OPERATOR_TOKEN" \
  -H 'content-type: application/json' -d '{"text":"ok"}'   # direct lane, no model
curl -s -X POST https://bars.thepaulieffect.com/chat ...   # real question → flash lane
```

Full gauntlet (visual, missions, memory, restart persistence, failure tests)
is in the PR body.

## Rollback

One git ref + one image:

```bash
docker rm -f bars
docker run -d --name bars ... bars-sovereign:<previous-SHA>
# or: cd /opt/bars/app && git checkout <previous-SHA> && rebuild
```

State survives rollback: everything durable lives in /opt/bars/data.

## Notes

- `hands.py` (machine control) is force-disabled (`BARS_DISABLE_HANDS=1`) —
  on the VPS it could only ever control the VPS, which is not wanted.
- The desktop floating presence (`presence.py`) never spawns headless; the
  browser 3D BARS is the presence layer here.
- Missions run on the internal worker (provider-only research/synthesis)
  because no coding CLI exists on the VPS. Reports say so truthfully.
- Paid model routes are fail-closed: they only run with `BARS_ALLOW_PAID=1`
  AND under `BARS_PAID_TOKEN_BUDGET` per day. Default: free Groq lanes only.
- Routing receipts: `/data/receipts.jsonl` (lane, model, tokens, ms, paid).
