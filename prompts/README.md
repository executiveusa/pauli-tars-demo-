# BARS prompt bundle

BARS vendors its shared constitution and full overlay from
`executiveusa/pauli-starnet` at the exact revision recorded in `SOURCE.json`.
Vendoring keeps startup deterministic and removes a network dependency from the
runtime.

`server.py` assembles the system prompt in this order:

1. `constitution.md`
2. `overlays/bars.md`
3. live FLAVOR and AUTHENTICITY settings, plus spoken-output constraints

The runtime settings narrow presentation only. They do not loosen a gate in the
constitution.

To sync from a new approved Pauli Starnet revision, replace the two files, update
`SOURCE.json`, and run:

```sh
python3 scripts/check_prompt_sync.py
```

Use `--remote` when network access is available to compare the vendored bytes
against the SHA-pinned GitHub source as well.
