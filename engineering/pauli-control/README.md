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

- Bearer `PAULI_CONTROL_TOKEN` on every route, compared in constant time.
- Jobs get an explicit environment: system basics, model-provider `*_API_KEY` keys, and names
  listed in `JOB_ENV_ALLOW`. The bridge token and other `*_TOKEN` / `*SECRET*` values never reach
  a job.
- Bind it to loopback or a private network; it is not a public service.

## Moving an existing deployment

The VPS service that ran from the Pi checkout keeps running until it is repointed. Change its
`WorkingDirectory` to this folder, run `npm ci`, and restart the service.
