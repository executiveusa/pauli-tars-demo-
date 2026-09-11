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
   - `BARS_ALLOWED_ORIGINS=https://barsdemo.netlify.app` (the cockpit itself is served same-origin via Caddy at https://bars.thepaulieffect.com, which needs no allowlist entry; only cross-origin callers are listed)
4. DNS: `bars.thepaulieffect.com` A record → `31.220.58.212`, DNS-only
   (grey cloud) in the Cloudflare zone `96712684919a639674c22fee58732ed9`.

## Deploy

```bash
cd /opt/bars
git clone https://github.com/executiveusa/pauli-tars-demo-.git app
cd app && git checkout <merged-main-SHA>   # full 40-char SHA, never a short ref
# Immutable image identity: tag is the exact 40-char SHA, provenance is baked
# at build time (/app/.bars_sha). No mutable tags, no env-echo identity.
export BARS_GIT_SHA=$(git rev-parse HEAD)
docker build --build-arg BARS_SHA=$BARS_GIT_SHA -t bars-sovereign:$BARS_GIT_SHA .
docker run -d --name bars --restart unless-stopped \
  --env-file /opt/bars/.env \
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

## Deploy / rollback (executable)

```bash
/opt/bars/app/deploy/deploy.sh <full-40-char-git-sha>  # snapshot data, build, health-gated swap
/opt/bars/app/deploy/rollback.sh             # image-only rollback (data/audit preserved)
/opt/bars/app/deploy/rollback.sh --with-data # also restore pre-deploy data snapshot
```

Both scripts are health-gated and use docker-compose.yml as the single source
of hardening (read-only rootfs, tmpfs /tmp, no-new-privileges, cap_drop ALL,
non-root uid 10001, mem/cpu/pids caps). The running SHA is recorded in
/opt/bars/current.sha; rollback records the abandoned SHA in
/opt/bars/rolled-back-from.sha. Durable state (receipts, budget ledger,
missions, memory) always lives in /opt/bars/data and is never touched by a
default rollback.

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

## Receipt anchor trust domain (security limitation)

The receipt ledger's rotation checkpoint anchor (`receipts.jsonl.anchor`) is
HMAC-protected: on read, the stored `seq/prev` must match an HMAC computed
from the same key as the chain itself. A corrupt or forged anchor, an anchor
missing for a non-empty ledger, or an anchor ahead of the chain state all put
the ledger in fail-closed mode: appends are refused and the finding is
surfaced on startup.

Limitation: by default the anchor lives inside the writable data domain
(`/opt/bars/data`), so an attacker with full data-write access could in
principle recompute the anchor if they also know the key (which they must
not, since the key comes from the env). To remove the anchor from the
writable data domain entirely, set `BARS_RECEIPT_ANCHOR_PATH` in the
environment (e.g. `/etc/bars/receipt.anchor` on a read-only-mounted file) so
the anchor file is stored outside `/data`. The HMAC check runs either way.

### Full-wipe trust limitation

The fail-closed checks cover anchor forgery, a missing/corrupt anchor or
state file, and runtime disappearance of either. They cannot cover an
attacker who wipes the ENTIRE data volume (ledger + state + anchor together):
a fresh empty ledger is indistinguishable from a fresh install. Mitigation is
operational: ship `receipts.jsonl` off-box (or snapshot `/opt/bars/data` and
`/opt/bars/anchor` independently) if receipt continuity must survive a full
data-volume compromise.

## Seventh-review deployment notes

- **Receipt HMAC key**: set `BARS_RECEIPT_KEY` (64+ hex chars) in
  `/opt/bars/.env` from Infisical (prod path `BARS_RECEIPT_KEY`). The env wins
  over the on-disk key file, so the chain key never has to live on the data
  volume. If unset, the server generates `/data/.receipts.key` (0600) as a
  dev fallback. A wrong/short env value fails closed at startup.
- **Receipt anchor**: compose mounts `/opt/bars/anchor:/anchor` and sets
  `BARS_RECEIPT_ANCHOR_PATH=/anchor/receipt.anchor`. Create the host dir once:
  `mkdir -p /opt/bars/anchor && chown 10001:10001 /opt/bars/anchor`.
- **Runtime identity**: the image bakes its git SHA at build time
  (`docker build --build-arg BARS_SHA=<sha>` writes `/app/.bars_sha`);
  `/health` and `/api/status` report that baked value. `BARS_GIT_SHA` is a
  dev fallback only. Rollback runs the immutable `bars-sovereign:<prev-sha>`
  image and verifies `/health` reports exactly that SHA.
- **Paid conversational mode**: chat and screen analysis are ungated ONLY
  while paid models are disabled by default. Setting `BARS_ALLOW_PAID=1`
  puts conversational inference itself behind explicit `chat.exec`/`chat.see`
  confirmations; do not enable it without an approved paid policy.
- **Front door**: `index.html` and `static/index.html` are one source kept in
  tested sync by `scripts/verify_frontdoor.py` (byte-identity check in CI).
