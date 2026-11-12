# Custodium Dashboard

Vue 3 + TypeScript (strict) + Vite + Tailwind CSS v3 + Pinia + Vue Router + TanStack Vue Query.

## Develop

```bash
npm install
npm run dev        # Vite on :5173, proxies /api -> http://localhost:8000
npm run typecheck  # vue-tsc --noEmit
npm test           # vitest (tests/Button.spec.ts, tests/auth.spec.ts)
npm run build
```

## Status (Phase 1)

Implemented and wired to `/api/v1`: login, register, overview, organizations
(list/create), projects (list/create), API keys (list/create/revoke — a new
secret is shown exactly once in memory only, never stored).

Wired forms: transaction hash lookup (`GET /transactions/lookup`),
assets/networks tables, sweep destination endpoint (`PUT /sweep-destination-endpoint`).

Clearly labelled placeholders (no fake data): wallets (Phase 2/3), addresses
(Phase 2), sweeps (Phase 10), blacklist (Phase 9/10), webhooks (Phase 9/11),
audit explorer (Phase 11).

Build was not run by the authoring agent if dependencies were not installed;
run the commands above to verify.
