# Custodium

Enterprise multi-chain **MPC Wallet-as-a-Service (WaaS)** — custodial wallet
infrastructure for exchanges, payment gateways, merchants and financial apps,
delivered as REST APIs and a SaaS dashboard.

> **Status (2026-11-12): Phase 0 Implemented, Phase 1 In Progress.**
> This platform is **not production-ready**. No real-value custody may be
> operated on it. Production signing does not exist yet and stays disabled
> until the MPC subsystem (Phase 3) is implemented and independently
> reviewed. See `AGENTS.md` for the phase table and the append-only
> history log every contributor/agent must keep updated.

## What exists today

- **Phase 0** — full architecture & security documentation under `docs/`
  (PRD, threat model, ERD, MPC protocol evaluation, chain capability matrix,
  API designs, ADRs, Phase 0–12 backlog).
- **Phase 1** — SaaS foundation:
  - Django 5.2 + Django Ninja API: registration, email verification,
    login/logout, password reset, organizations, team memberships,
    projects (sandbox/production), API keys with HMAC-SHA256 machine
    authentication (timestamp + nonce replay protection), tenant isolation,
    audit log, seeded network/asset registry (Ethereum, BSC, TRON, Solana,
    TON + verified USDT identities — BSC USDT is Binance-Peg, not
    Tether-native).
  - Vue 3 + TypeScript dashboard (see `apps/dashboard/DESIGN.md`).
  - Rust MPC workspace **skeleton** (`services/mpc/`) — fail-closed;
    threshold signing returns `NotImplemented` until reviewed libraries
    are integrated in Phase 3.
  - Endpoints whose subsystems land later (transaction lookup → Phase 5,
    sweep destination endpoint → Phase 10) return HTTP 501 rather than
    fabricated data.

## Quick start (local development)

Prerequisites: Python 3.12 + [`uv`](https://docs.astral.sh/uv/), Node 20+,
and Docker (for the Compose stack) — or run the backend directly on SQLite.

```bash
# Backend
cd apps/backend
uv sync --group dev
DJANGO_SETTINGS_MODULE=config.settings.development uv run python manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.development uv run python manage.py seed_networks_assets
DJANGO_SETTINGS_MODULE=config.settings.development uv run python manage.py runserver

# Frontend (proxies /api to localhost:8000)
cd apps/dashboard
npm install
npm run dev

# Or everything (Postgres, Redis, Temporal, backend, dashboard)
docker compose up --build
```

Run backend tests/lint: `cd apps/backend && uv run pytest && uv run ruff check .`

## Repository layout

See the Master Engineering Prompt structure: `apps/` (backend, dashboard),
`services/mpc/` (Rust), `packages/` (proto, contracts, SDKs),
`infrastructure/`, `docs/`, root `tests/`, `scripts/`.

## Working rules (binding)

Develop each phase locally → verify → commit **all** of that phase's files
in **one commit** → push → merge to `main`. Record every work session in
`AGENTS.md` (phase status + dated history entry: what was done, what was
actually verified, what was not, what remains).

Security non-negotiables — no fake MPC, no private shares in app databases
or logs, sweep destinations only from a tenant's registered HTTPS resolver
endpoint, manual blacklist only (not an AML system), exact integer money
with a double-entry ledger — are listed in `AGENTS.md` and `docs/security/`.
