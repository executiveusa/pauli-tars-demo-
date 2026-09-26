# BARS engineering bridge (`pauli-control`)

Runs coding-agent jobs (the `pi` CLI) inside allowlisted repos, with plan / read / write / ship
modes. Write and ship are off unless `ALLOW_WRITE=1` / `ALLOW_SHIP=1`.

It moved here from `pauli-pi-agent/ops/pauli-control` on 2026-09-26, when Pi became the owner's
personal-only agent and engineering work moved to BARS. Terabithia routes `engineering` missions
to BARS (`terabithia_adapter.py` accepts the `engineering` route).

## Run

```sh
cd engineering/pauli-control
npm ci
PAULI_CONTROL_TOKEN=<32+ chars> PAULI_WORKSPACE_ROOT=/srv/repos npm start   # port 8787 by default
```

## Security

- Bearer `PAULI_CONTROL_TOKEN` on every route except `/health`, which only reports liveness.
  Tokens are compared in constant time.
- Jobs get an explicit environment: system basics, model-provider `*_API_KEY` keys, and names
  listed in `JOB_ENV_ALLOW`. The bridge token, other `*_TOKEN` / `*SECRET*` values and Pi's
  personal-lane keys (`PAULI_PI_*`, `PI_*`, `*PERSONAL*`) never reach a job.
- The agent is spawned without a shell, so task text is passed as literal arguments.
- `repo` must resolve, after following symlinks, inside `PAULI_WORKSPACE_ROOT`.
- `timeoutMinutes` must be 1-120; `model`, `provider` and `thinking` are plain identifiers.
- Job records live in `jobs/` (or `PAULI_CONTROL_JOB_DIR`); job ids are UUIDs.
- Tests: `npm test`.

## Terabithia

The BARS Terabithia adapter (`terabithia_adapter.py`) sends `route: engineering` missions here as
`POST /run` (plan mode unless the mission sets `mode` to read/write/ship). Set
`PAULI_CONTROL_URL` and `PAULI_CONTROL_TOKEN` on the adapter. If they are unset, the adapter
refuses engineering missions with 503 instead of accepting work it cannot do. Write and ship
still require `ALLOW_WRITE=1` / `ALLOW_SHIP=1` on this bridge.
- Bind it to loopback or a private network; it is not a public service.

## Moving an existing deployment

The VPS service that ran from the Pi checkout keeps running until it is repointed. Change its
`WorkingDirectory` to this folder, run `npm ci`, and restart the service.
