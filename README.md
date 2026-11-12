# Custodium

**Enterprise multi-chain MPC Wallet-as-a-Service (WaaS).**

Custodium is custodial wallet infrastructure for centralized exchanges,
payment gateways, merchant platforms, and financial applications. It provides
multi-chain MPC wallets, a double-entry custody ledger, policy-controlled
withdrawals, resolver-based sweeping, signed webhooks, and a complete SaaS
console — behind HMAC-authenticated REST APIs.

[![CI](https://github.com/zeroexlive/Custodium/actions/workflows/ci.yml/badge.svg)](https://github.com/zeroexlive/Custodium/actions/workflows/ci.yml)

> ### ⚠️ Status — pre-production
>
> All 13 development phases (0–12) are implemented, tested, and merged.
> Custodium is **not Production Approved**: production signing remains
> **disabled** pending an independent cryptographic/security review, and no
> real-value custody may be operated on this codebase until the gates in
> [`docs/architecture/phase-12-hardening.md`](docs/architecture/phase-12-hardening.md)
> are closed and a written production approval decision exists. This
> repository makes no production-readiness claim beyond what its records
> verify — see the readiness assessment before evaluating further.

---

## Highlights

- **Five chains, one API** — Ethereum, BNB Smart Chain, TRON, Solana, and
  TON, with native assets, arbitrary tokens, and first-class USDT support.
- **Threshold cryptography, honestly gated** — MPC key management built on
  evaluated Rust implementations (CGGMP-family threshold ECDSA, FROST
  Ed25519). The Django tier never holds key material and can never sign
  unilaterally; only fail-closed signer adapters ship until the independent
  review lands.
- **Double-entry custody ledger** — exact integer amounts (no floats),
  append-only journal enforced at the model *and* database level,
  journal-backed reservations, and continuous reconciliation with
  fail-closed halts.
- **Policy-controlled withdrawals** — maker–checker approvals, per-asset
  and project policies, hard single/daily limits, service-fee accounting,
  and refund playbooks.
- **Sweeps that can't be redirected** — destinations come only from a
  tenant-registered HTTPS resolver endpoint (SSRF-hardened), are snapshotted
  immutably before approval, and are never accepted in a sweep request.
- **Gas station** — per-project, per-network automatic native-coin
  top-ups: when a wallet's on-chain native balance falls below a
  configured threshold, a funding wallet tops it up through the normal
  transfer pipeline and the pending withdrawal or sweep proceeds.
- **Production-shaped operations** — signed webhooks with retries and
  replay, plans/quotas/billing, audit exports, a platform kill switch,
  health/readiness probes, and incident-response runbooks.

## Supported networks & USDT

Token identity in Custodium is always *network + contract/mint/master
address*, never a symbol. The seeded registry carries these verified USDT
identities:

| Network | USDT identity | Decimals | Variant |
|---|---|---|---|
| Ethereum | `0xdAC17F958D2ee523a2206206994597C13D831ec7` | 6 | Tether-native (ERC-20) |
| BNB Smart Chain | `0x55d398326f99059fF775485246999027B3197955` | 18 | Binance-Peg (BEP-20), **not** Tether-native |
| TRON | `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` | 6 | Tether-native (TRC-20) |
| Solana | `Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB` | 6 | Tether-native (SPL) |
| TON | `EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs` | 6 | Tether-native (Jetton) |

## Architecture

Custodium is a modular monolith with isolated cryptographic services and
dedicated blockchain workers. Tenant context is always derived from the
authenticated identity — never from request bodies.

```mermaid
flowchart LR
    subgraph Tenants
        API[HMAC REST API clients]
        UI[SaaS Dashboard]
    end
    subgraph Platform["Custodium platform (Django modular monolith)"]
        CORE[Wallets · Ledger · Indexing<br/>Withdrawals · Sweeps · Webhooks]
        OPS[Plans & Billing · Audit · Kill switches]
    end
    subgraph Crypto["Isolated MPC tier (Rust)"]
        MPC[Threshold ECDSA · FROST Ed25519<br/>fail-closed until reviewed]
    end
    subgraph Workers
        IDX[Chain indexers / scanners]
        DSP[Withdrawal & sweep dispatch]
        WH[Webhook delivery]
    end
    CHAINS[(ETH · BSC · TRON · Solana · TON)]
    API --> CORE
    UI --> CORE
    CORE --> OPS
    CORE -. signing requests only .-> MPC
    IDX --> CHAINS
    DSP --> CHAINS
    IDX --> CORE
    WH --> Tenants
```

Design records: [`docs/architecture/`](docs/architecture/) ·
ADRs: [`docs/adr/`](docs/adr/) · Threat model:
[`docs/security/`](docs/security/).

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Django 5.2 LTS, Django Ninja, PostgreSQL, Redis |
| Frontend | Vue 3, TypeScript (strict), Vite, Tailwind CSS, Pinia, TanStack Vue Query |
| Cryptography | Rust — CGGMP-family threshold ECDSA, FROST Ed25519 (evaluation harness; see [`docs/mpc/`](docs/mpc/)) |
| Workers | Idempotent management-command entrypoints (`run_indexer`, `process_withdrawals`, `process_sweeps`, `deliver_webhooks`, `run_reconciliation`) |
| Tooling | `uv` (Python), npm, Cargo; GitHub Actions CI |

## Quick start

### Prerequisites

- Python 3.12+ with [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- Optional: Docker (full Compose stack), Rust toolchain (MPC harness only)
- Production: PostgreSQL 15+ (development defaults to SQLite)

### Option A — local development (fastest)

**Automated:** the interactive installer performs the whole
single-server setup step by step, with confirmations:

```bash
git clone https://github.com/zeroexlive/Custodium.git
cd Custodium
bash scripts/install.sh         # --dry-run previews, --yes accepts defaults
```

Tutorial: [`docs/operations/deployment-1-server-dev.md`](docs/operations/deployment-1-server-dev.md).
Manual equivalent:

```bash
git clone https://github.com/zeroexlive/Custodium.git
cd Custodium

# Backend (SQLite by default in development settings)
cd apps/backend
uv sync --group dev
uv run python manage.py migrate
uv run python manage.py seed_networks_assets   # networks + verified assets
uv run python manage.py seed_plans              # Sandbox / Growth / Scale plans
uv run python manage.py createsuperuser         # optional: Django admin/staff
uv run python manage.py runserver               # http://localhost:8000

# Dashboard (separate terminal; proxies /api to localhost:8000)
cd apps/dashboard
npm install
npm run dev                                     # http://localhost:5173
```

Register a user from the dashboard, create an organization and project,
then issue an API key (the secret is shown exactly once) to call the API —
see *Authentication* below.

### Option B — Docker Compose (PostgreSQL + Redis + Temporal dev server)

```bash
docker compose up --build
# dashboard → http://localhost:5173 · API → http://localhost:8000
```

> The Compose stack is a development convenience; production topology is
> covered in [`docs/architecture/`](docs/architecture/) and the rollout
> plan in [`docs/operations/mainnet-rollout-plan.md`](docs/operations/mainnet-rollout-plan.md).

### Worker processes

State machines advance through idempotent worker entrypoints (run them on a
schedule or under your orchestrator; Temporal integration is a deployment
step — see the readiness assessment):

```bash
uv run python manage.py run_indexer --network ethereum   # deposit scanning
uv run python manage.py process_withdrawals              # dispatch + refresh
uv run python manage.py process_sweeps                   # resolve + execute
uv run python manage.py deliver_webhooks                 # signed deliveries
uv run python manage.py run_reconciliation               # ledger vs chain
```

## Configuration

Configuration is environment-driven. Production settings
(`config.settings.production`) refuse to boot with placeholder secrets.

| Variable | Required | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | prod | Django secret key (≥ 50 random chars) |
| `DATABASE_URL` | prod | e.g. `postgres://user:pass@host:5432/custodium` |
| `WAAS_SECRET_ENCRYPTION_KEY` | prod | Fernet key encrypting API/webhook/resolver secrets at rest — provision from KMS/Vault |
| `DJANGO_ALLOWED_HOSTS` | prod | Comma-separated host allow-list |
| `REDIS_URL` | no | Cache/queue backend (default `redis://localhost:6379/0`) |
| `DJANGO_SETTINGS_MODULE` | no | `config.settings.{development,production,testing}` |
| `LOG_LEVEL` | no | Default `INFO` |

## API overview

Base path: `/api/v1/`. Machine authentication is HMAC-SHA256 over a
canonical request string with timestamp + nonce replay protection; dashboard
authentication is a bearer session token. Amounts are always integer strings
in the asset's base units.

| Area | Examples |
|---|---|
| Wallets & balances | `POST /wallets`, `GET /wallets/{id}/balances`, `GET /projects/{id}/balances` |
| Deposits & lookup | `GET /deposits`, `GET /transactions/lookup?network=…&hash=…` |
| Withdrawals | `POST /withdrawals` (Idempotency-Key required), `…/approve`, `…/reject`, `…/refund`, policy `GET/PUT /projects/{id}/withdrawal-policy` |
| Sweeps | `POST /sweeps` (**no destination field — by design**), `PUT /sweep-destination-endpoint`, `POST /sweep-destination-endpoint/test` |
| Webhooks | `POST /webhooks/endpoints`, `GET /webhooks/deliveries`, `…/replay` |
| Billing | `GET /plans`, `GET /organizations/{id}/usage`, `GET /organizations/{id}/invoices` |
| Operations | `GET/POST /operator/platform-halt` (staff), `/healthz`, `/readyz` (root path) |

**Integration documents**

- Authentication & HMAC scheme — [`docs/api/authentication.md`](docs/api/authentication.md)
- HMAC test vectors (asserted by the test suite) — [`docs/api/hmac-test-vectors.md`](docs/api/hmac-test-vectors.md)
- SDK examples (Python stdlib, Node) — [`docs/api/sdk-examples.md`](docs/api/sdk-examples.md)
- Webhook contract — [`docs/api/webhooks.md`](docs/api/webhooks.md)
- Sweep resolver specification (normative) — [`docs/api/sweep-resolver.md`](docs/api/sweep-resolver.md)
- Wallet API reference — [`docs/api/wallet-api.md`](docs/api/wallet-api.md)

Interactive schema: Django Ninja serves OpenAPI at `/api/v1/openapi.json`
with Swagger UI at `/api/v1/docs` in development.

## Testing

```bash
# Backend — 167 passed, 1 skipped (PostgreSQL-only wei-scale case)
cd apps/backend && uv run pytest && uv run ruff check .

# MPC evaluation harness — 16 passed
cd services/mpc && cargo test --workspace

# Dashboard — typecheck + unit tests + production build
cd apps/dashboard && npx vue-tsc --noEmit && npx vitest run && npm run build
```

Chain integrations are verified against in-process provider doubles,
differential tests against the official client libraries (e.g. `@ton/ton`),
and cross-implementation signature proofs — live-network verification status
per chain is recorded in [`docs/blockchains/`](docs/blockchains/) and the
readiness assessment.

## Security

- **No key material in the application tier** — shares never touch
  PostgreSQL, logs, or API responses; the API tier requests signatures
  through a fail-closed port only.
- **Append-only money history** — journal, audit trail, and sweep
  destination snapshots are immutable at the database level.
- **SSRF-hardened outbound calls** — sweep resolver and webhook delivery
  enforce HTTPS + public-IP DNS validation on every call.
- **Manual blacklist only** — Custodium deliberately ships no AML/KYT
  claims; screening beyond the operator-curated list is an integration
  decision for the operator.
- Full model: [`docs/security/`](docs/security/) · MPC evaluation and the
  independent-review package: [`docs/mpc/`](docs/mpc/).

To report a vulnerability, open a private security advisory on GitHub
rather than a public issue.

## Repository layout

```text
apps/backend/     Django + Ninja API (modular monolith, waas/modules/*)
apps/dashboard/   Vue 3 SaaS console
services/mpc/     Rust MPC workspace (evaluation harness + fail-closed skeleton)
docs/             PRD, architecture, ADRs, API specs, chain records, runbooks
tests/            Cross-cutting test material
scripts/          Developer/operator scripts
infrastructure/   Deployment assets
```

## Documentation

Start with the [product requirements](docs/prd/product-requirements.md),
the [roadmap & phase records](docs/roadmap/backlog.md), and the
[operations runbooks](docs/operations/) — including the deployment
tutorials: [one-server development](docs/operations/deployment-1-server-dev.md)
and the [six-server minimum production topology](docs/operations/deployment-6-server.md).
`AGENTS.md` carries the binding
contribution rules and the append-only engineering history — every work
session records what was done, what was actually verified, and what remains.

## Development workflow

Phases are developed locally, verified, committed as **one commit per
phase**, pushed, and merged to `main` via pull request. Never commit
unverified work; never describe a feature beyond its evidenced maturity
(Planned → Implemented → Tested → Security Reviewed → Production Approved).

---

© 2026 Custodium contributors. All rights reserved.
