# BARS / TARS Security Boundaries

## Non-Negotiable Security Rules
1. **Zero Public Localhost Ports**: Ports `4321`, `4323`, and `4324` are strictly bound to loopback `127.0.0.1`.
2. **Outbound-Only Communication**: Worker node `bambu-windows-01` polls Terabithia Control Plane outbound using TLS HTTPS (`https://api.thepaulieffect.com/terabithia`).
3. **Separated Authentication**:
   - Authority requests require `TERABITHIA_API_KEY`.
   - Worker requests require `BARS_REMOTE_TOKEN`.
   - Worker never holds or logs `TERABITHIA_API_KEY`.
4. **Constrained Hands & Tools**:
   - Destructive commands (`rm -rf`, format disk, credential modification) are blocked.
   - Bounded coding tools operate exclusively in designated project directories or branch sandboxes.
5. **No Credential Leakage**: Secret values are never printed in logs, receipts, or mission reports (names and presence only).
