# Security Policy

Custodium is custody infrastructure under active development and is **not
production-ready**. Do not operate it with real funds.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the repository owner
(GitHub: `zeroexlive`) — do not open a public issue for an exploitable
flaw. Include reproduction steps, affected components, and impact.

## Security model

The authoritative documents are:

- `docs/security/threat-model.md` — STRIDE threat model and residual risks
- `docs/security/tenant-isolation.md`
- `docs/security/incident-response.md`
- `docs/mpc/signer-security.md` — signing policy and intent binding
- `docs/api/authentication.md` — dashboard + HMAC machine authentication

Key invariants: threshold signing only (never a reconstructed private
key), independent signer policy verification, append-only double-entry
ledger, tenant isolation at every layer, and sweep destinations resolved
only from a tenant's registered HTTPS endpoint — never from requests or
local configuration.
