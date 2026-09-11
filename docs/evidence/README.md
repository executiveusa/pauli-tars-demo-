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

Current attested run: see `docker-integration-b77e92dd.json` (+ committed raw
log and context file, byte-identical to the CI artifact). Verify runs at:
https://github.com/executiveusa/pauli-tars-demo-/actions/workflows/docker-integration.yml
