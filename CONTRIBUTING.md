# Contributing to Custodium

## Binding workflow

1. Read `AGENTS.md` first — rules, phase status, history log.
2. Develop **one phase at a time**, locally.
3. Verify locally: backend `uv run pytest` + `uv run ruff check .`,
   frontend `npm run typecheck && npm test && npm run build`.
   Never report a check you did not run.
4. Update `AGENTS.md`: phase status + a dated history entry (done /
   verified / not verified and why / remaining).
5. Commit **all** of the phase's files in **one commit**, push, merge to
   `main`. Keep `main` stable; no piecemeal commits per phase.

## Hard rules

- No mock/fake cryptography in signing paths; no single-key signing
  presented as MPC.
- No secrets, private shares, or API secrets in code, logs, tests or docs.
- Money: integer base units only, never floats.
- Tenant isolation: authorization context comes from authentication,
  never from request bodies.
- Documentation must not describe unimplemented features as complete.
