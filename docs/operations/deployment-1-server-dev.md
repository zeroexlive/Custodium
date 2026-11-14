# Tutorial — One-Server Development Deployment

> **Superseded** by [installation-dev.md](installation-dev.md) (2026-11-13) — kept for
> history; follow the new tutorial.


The complete Custodium stack on a **single server**: PostgreSQL,
Redis, the Temporal development server, the Django API, the Vue
dashboard, and the worker commands. This is the right topology for
development, evaluation, demos, staging, and testnet pilots — and
the wrong one for real-value custody (see *Limitations* below).

Two ways to run it:

- **Automated:** `bash scripts/install.sh` — an interactive,
  step-by-step installer that performs this whole tutorial with
  confirmations.
- **Manual:** the steps below (identical outcome).

## Prerequisites

- One Linux server/VM: **4 vCPU / 8 GB RAM / 40 GB SSD** recommended
  (2 vCPU / 4 GB works for light evaluation).
- Docker Engine + Compose plugin **(path A)**, *or* Python 3.12 with
  [`uv`](https://docs.astral.sh/uv/) and Node.js 20+ **(path B)**.
- Git, curl. Outbound HTTPS for package registries and chain RPC
  providers.

## Path A — Docker Compose (recommended)

```bash
git clone https://github.com/zeroexlive/Custodium.git
cd Custodium
cp .env.example .env
```

Edit `.env` — for a dev box the defaults work, but set a real
`POSTGRES_PASSWORD` and generate the secret-encryption key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → paste into WAAS_SECRET_ENCRYPTION_KEY=  (required even in dev:
#   API keys, webhook and resolver secrets are encrypted with it)
```

Start everything:

```bash
docker compose up --build -d
docker compose ps        # postgres, redis, temporal, backend, dashboard
```

The backend container runs migrations and seeds the network/asset
registry on start. Then:

| Surface | URL |
|---|---|
| Dashboard | http://localhost:5173 |
| API | http://localhost:8000/api/v1/ |
| Health / readiness | http://localhost:8000/healthz · `/readyz` |
| Temporal dev UI | http://localhost:8233 |

## Path B — Native (no Docker, SQLite)

```bash
git clone https://github.com/zeroexlive/Custodium.git
cd Custodium

cd apps/backend
uv sync --group dev
uv run python manage.py migrate
uv run python manage.py seed_networks_assets
uv run python manage.py seed_plans
uv run python manage.py runserver 0.0.0.0:8000      # terminal 1

cd ../../apps/dashboard
npm install
npm run dev                                          # terminal 2 → :5173
```

Development settings default to SQLite and
`DJANGO_SETTINGS_MODULE=config.settings.development` is the
`manage.py` default, so no environment setup is needed for a first
run. Set `WAAS_SECRET_ENCRYPTION_KEY` (see Path A) before creating
API keys — secret encryption must be configured for keys to be
issued.

## First-run walkthrough (both paths)

1. There is **no public registration**. Create the platform owner
   once with `manage.py createsuperuser`, sign in, and create
   customer accounts from the dashboard **Customers** page — each
   customer receives a generated temporary password by email (and
   shown to the admin once). Customers only ever sign in.
2. Create an **organization**, then a **project** (environment:
   `sandbox` for testnets).
3. **API Keys → Create**: choose scopes (start with `read`,
   `wallets:write`, `withdrawals:write`). Copy the secret **now** —
   it is shown exactly once.
4. Create a wallet. It appears as `provisioning`: address derivation
   is gated on the MPC review, by design — on a dev box this is the
   expected state, not an error.
5. Make your first signed call using the examples in
   `docs/api/sdk-examples.md` (verify your signer against
   `docs/api/hmac-test-vectors.md` first).
6. Explore: register a webhook endpoint (Webhooks view), check the
   plan/usage (Billing view), and review the audit log export.

## Running the workers

Workers are idempotent management commands. In Compose they are not
long-running services by default — run them on demand or add them as
cron/systemd jobs on the host:

```bash
# via Compose:
docker compose exec backend python manage.py run_indexer --network ethereum
docker compose exec backend python manage.py process_withdrawals
docker compose exec backend python manage.py process_sweeps
docker compose exec backend python manage.py deliver_webhooks
docker compose exec backend python manage.py run_reconciliation

# natively: same commands via `uv run python manage.py …`
```

Networks: `ethereum`, `bsc`, `tron`, `solana`, `ton` (+ `-sepolia`,
`-testnet`, `-nile`, `-devnet` variants for testnets). On a dev box
the indexers will try to reach public RPC endpoints — if your server
has no chain egress, deposit scanning simply finds nothing; the rest
of the platform works offline.

## Verifying your install

```bash
curl localhost:8000/healthz     # {"status":"ok"}
curl localhost:8000/readyz      # {"status":"ready"}
cd apps/backend && uv run pytest          # 178 passed, 1 skipped
cd apps/dashboard && npx vitest run       # 9 passed
```

## Troubleshooting

**The dashboard loads, but login (any API action) shows
error 500.** The page loading only proves the *dashboard*
container is up — API calls go through its proxy to the backend,
and a dead backend surfaces as a proxy 500. Work from the API
outward:

```bash
docker compose ps                    # is backend "up (healthy)"?
docker compose logs --tail=80 backend
curl -X POST localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"a@b.co","password":"wrong-password"}'   # 401 from a live backend (bad credentials) proves it is up; a 500 means it is not
```

- The `curl` returns **401** → the backend is fine; the problem
  is the dashboard→backend path (check `docker compose logs
  dashboard` and that the stack was built from a current checkout).
- The `curl` also fails, or `backend` is `Restarting`/`Exited` →
  the last lines of the backend log hold the cause. The most
  common one: **database credentials mismatch.** Compose applies
  `POSTGRES_PASSWORD` only when the postgres volume is *first*
  created; changing it later in `.env` does not change the
  password inside the existing volume, so the backend cannot
  connect and dies in `migrate`. Fix by restoring the original
  password in `.env`, or — if no data matters yet — reset:
  `docker compose down -v && docker compose up --build`
  (the `-v` deletes the database volume).
- `curl localhost:8000/readyz` returning 503 means the API
  process is up but cannot reach PostgreSQL — same credential /
  volume family of causes.

## Limitations of one server (read before graduating)

- **No MPC separation.** With everything on one host, threshold
  signing could never provide its guarantee — one breach would
  reach every component. This is why signing ships disabled and why
  the [six-server topology](deployment-6-server.md) puts each share
  on its own host.
- **Single point of failure** for API, database, and workers.
- **Resource contention**: indexers and the API share CPU during
  chain bursts.
- The Temporal container is the single-binary **dev server** —
  fine here, not a production Temporal deployment.

Graduation path: keep the same `.env` discipline and commands; the
six-server tutorial splits exactly these components apart.
