# Docker integration evidence

The earlier committed receipt (`docker-integration-68783fb6.json`) was
WITHDRAWN: it was self-attestation (the raw log was deleted and its hash
could not independently prove the claimed run).

Evidence is now produced by an independent execution surface: the
`Docker Integration (isolated)` GitHub Actions workflow runs
`tests/test_deploy_docker.sh` on an ephemeral GitHub-hosted runner on every
push to `fix/bars-sovereign-runtime` (no secrets, no credentials, no live
contact). Each run uploads `docker-integration.log` (full raw test output:
isolation preflight, deploy/rollback health identity sequence, teardown) and
`run-context.txt` (run start/end UTC, exact code SHA, test script sha256) as
the `docker-integration-evidence` artifact.

Byte binding: each run prints the sha256 of the raw log and context file into
the public run log and the check-run step summary and ships them as
`evidence-hashes.txt` in the artifact; the committed copies are byte-identical,
so the committed evidence is bound to independently observable run output.

Current attested run: see `docker-integration-ad214454.json` (+ committed raw
log, context file, and published hashes, byte-identical to the CI artifact).
Verify runs at:
https://github.com/executiveusa/pauli-tars-demo-/actions/workflows/docker-integration.yml
