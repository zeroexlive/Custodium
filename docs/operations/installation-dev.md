# Installation Tutorial — Development

Set up Custodium for **development, evaluation, demos, and
testnet pilots**. Four paths, in increasing fidelity:

| Path | What runs | Use it for |
|---|---|---|
| A. Installer | Everything below, automated | first look on a dev server |
| B. Docker Compose | Full stack in containers on one host | staging-like dev, demos |
| C. Native local | Backend + dashboard from the checkout | day-to-day development |
| D. Local signer cluster | + 3 signer nodes on loopback | provisioning/signing work, rehearsals |

> Signing on a dev box is for **development keys only**. Nothing
> here authorizes real funds: production signing stays behind
> the independent review (see
> [installation-production.md](installation-production.md)).

## Prerequisites

- Linux or macOS; a server/VM for paths A/B wants **4 vCPU /
  8 GB RAM / 40 GB SSD** (2 vCPU / 4 GB works for light use).
- Git, curl.
- Path B: Docker Engine + Compose plugin.
- Path C/D: Python **3.12+** with [uv](https://docs.astral.sh/uv/),
  Node.js **20+** with npm.
- Path D additionally: a Rust toolchain (`rustup`, stable) for
  building the signer, and ~4 GB free for the build tree.
- Outbound HTTPS for package registries; chain RPC endpoints if
  you want live testnet scanning.

## Path A — Automated installer (dev server)

```bash
git clone https://github.com/zeroexlive/Custodium.git
cd Custodium
bash scripts/install.sh        # --dry-run previews, --yes accepts defaults
```

The installer performs the Compose setup (Path B) step by step
with confirmations: environment file with fresh secrets,
migrations, registry/plan seeds, optional superuser, health
probes.

## Path B — Docker Compose (one host)

```bash
git clone https://github.com/zeroexlive/Custodium.git
cd Custodium
cp .env.example .env
```

Set a real `POSTGRES_PASSWORD`, and generate the secret
encryption key (required even in dev — API-key, webhook, and
resolver secrets are encrypted with it):

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste into WAAS_SECRET_ENCRYPTION_KEY=
```

Start the stack (the backend container migrates and seeds on
start, and the dashboard waits for the backend to be healthy):

```bash
docker compose up --build -d
docker compose ps
```

| Surface | URL |
|---|---|
| Dashboard | http://localhost:5173 |
| API | http://localhost:8000/api/v1/ |
| Health / readiness | http://localhost:8000/healthz · `/readyz` |
| Temporal dev UI | http://localhost:8233 |

## Path C — Native local development

```bash
git clone https://github.com/zeroexlive/Custodium.git
cd Custodium

# Backend (SQLite by default under development settings)
cd apps/backend
uv sync --group dev
uv run python manage.py migrate
uv run python manage.py seed_networks_assets   # networks + verified assets
uv run python manage.py seed_plans              # Sandbox / Growth / Scale
uv run python manage.py runserver               # terminal 1 → :8000

# Dashboard (proxies /api to :8000)
cd ../../apps/dashboard
npm install
npm run dev                                     # terminal 2 → :5173
```

Set `WAAS_SECRET_ENCRYPTION_KEY` in your shell environment
before creating API keys (Path B shows how to generate one).

Run the test suites before and after your changes:

```bash
cd apps/backend && uv run pytest          # 208 passed, 1 skipped
uv run ruff check waas tests
cd apps/dashboard && npx vitest run       # frontend tests
npm run build                             # production build check
```

## Path D — Local signer cluster (development keys only)

The production signer is a Rust service; one process per
participant. On a dev machine all three run on loopback — the
threshold ceremonies are real, the isolation is not.

```bash
# 1) Build (from the repo root; first build takes several minutes)
cd services/mpc && cargo build -p custodium-signer-service
BIN=$PWD/target/debug/custodium-signer

# 2) Per-node state: separate store dirs + separate store keys
for i in 0 1 2; do
  mkdir -p ~/custodium-dev-signer/node$i
  openssl rand -hex 32 > ~/custodium-dev-signer/node$i/store.key
  chmod 600 ~/custodium-dev-signer/node$i/store.key
done
API_TOKEN=$(openssl rand -hex 16); CLUSTER_TOKEN=$(openssl rand -hex 16)
echo "API_TOKEN=$API_TOKEN CLUSTER_TOKEN=$CLUSTER_TOKEN" > ~/custodium-dev-signer/tokens

# 3) Start the three nodes (ports 8401-8403)
for i in 0 1 2; do
  SIGNER_PARTY_INDEX=$i \
  SIGNER_PEERS=http://127.0.0.1:8401,http://127.0.0.1:8402,http://127.0.0.1:8403 \
  SIGNER_BIND=127.0.0.1:$((8401+i)) \
  SIGNER_STORE_DIR=~/custodium-dev-signer/node$i \
  SIGNER_STORE_KEY_FILE=~/custodium-dev-signer/node$i/store.key \
  SIGNER_API_TOKEN=$API_TOKEN SIGNER_CLUSTER_TOKEN=$CLUSTER_TOKEN \
  $BIN > ~/custodium-dev-signer/node$i.log 2>&1 &
done
curl localhost:8401/healthz   # {"status":"ok"} on each port
```

Point the backend at the cluster and open the gate **for this
dev shell only**:

```bash
cd apps/backend
export MPC_SIGNER_ENABLED=true
export MPC_SIGNER_URL=http://127.0.0.1:8401
export MPC_SIGNER_TOKEN=$API_TOKEN
uv run python manage.py runserver
```

Or skip the manual setup entirely and run the scripted
end-to-end rehearsal (3 nodes + backend + API journey +
independent address/signature verification):

```bash
apps/backend/.venv/bin/python scripts/rehearse_provisioning.py
```

Details and the recorded run:
[provisioning-rehearsal.md](provisioning-rehearsal.md).

## First-run walkthrough (all paths)

1. Open the dashboard → **Register** (dev email verification is
   logged / returned in responses, not mailed).
2. Create an **organization**, then a **project** (environment
   `sandbox` for testnets).
3. *(Recommended)* enable **two-factor authentication** for your
   account once your dashboard build includes the 2FA view, or
   via the API: `POST /api/v1/auth/2fa/setup` then
   `/auth/2fa/enable` with a TOTP code (see
   `docs/api/authentication.md` §6b).
4. **API Keys → Create**: scopes to start: `read`,
   `wallets:write`, `withdrawals:write`. Copy the secret now —
   shown exactly once. Optionally set an IP allowlist / expiry.
5. Create a **wallet**. Without a signer (paths A–C) it stays
   `provisioning` — expected, not an error. With Path D running,
   provision it from the wallet view (or
   `uv run python manage.py provision_wallet <wallet-id>`): two
   real DKGs run (the ECDSA one takes a few minutes — aux-info
   generation dominates), addresses appear for all 10 networks,
   and the wallet turns `active`.
6. Make a signed API call using `docs/api/sdk-examples.md`;
   verify your HMAC implementation against
   `docs/api/hmac-test-vectors.md` first.
7. Explore: webhook endpoints + secret rotation, the destination
   address book, auto-sweep rules, gas-station config, plan usage
   and the audit export.

## Workers (on demand)

Workers are idempotent management commands — run them in a
terminal, or via Compose (`docker compose exec backend python
manage.py …`):

```bash
uv run python manage.py run_indexer --network ethereum   # + bsc, tron, solana, ton (+ testnet slugs)
uv run python manage.py process_withdrawals
uv run python manage.py process_sweeps
uv run python manage.py run_auto_sweeps
uv run python manage.py deliver_webhooks
uv run python manage.py run_reconciliation
```

Indexers reach out to public RPC endpoints; without chain
egress they simply find nothing — the rest of the platform works
offline.

## Verifying the install

```bash
curl localhost:8000/healthz     # {"status":"ok"}
curl localhost:8000/readyz      # {"status":"ready"}
```

## Troubleshooting

**Dashboard loads but register/login (any API action) shows
500.** The page loading proves only the *dashboard* is up; API
calls proxy to the backend, and a dead backend surfaces as a
proxy 500. Work outward from the API:

```bash
docker compose ps                    # backend "up (healthy)"?
docker compose logs --tail=80 backend
curl -X POST localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"a@b.co","password":"<redacted>","display_name":"A"}'
```

- `curl` returns **201** → backend is fine; check the dashboard
  logs / rebuild from a current checkout.
- Backend `Restarting`/`Exited` → the log tail names the cause.
  Most common: **database credential mismatch** — Compose sets
  the Postgres password only when the volume is *first created*;
  changing `POSTGRES_PASSWORD` afterwards strands the backend.
  Restore the original password, or reset dev data:
  `docker compose down -v && docker compose up --build`.
- `/readyz` 503 = API up, database unreachable — same family.

**Provision returns 409 "signer gate is closed".** Both
`MPC_SIGNER_ENABLED=true` **and** `MPC_SIGNER_URL` must be set
in the backend's environment; check the signer nodes are
healthy (`/healthz` on each) and the API token matches.

**Signer node exits immediately.** Check its log: the usual
causes are a store key file that isn't 64 hex chars / 32 raw
bytes, or a peer list that doesn't include its own address.

## Limitations

One host means **no threshold isolation** — Path D rehearses
protocol behaviour, not the security property. Single point of
failure, shared resources, and the Compose Temporal container
is the dev server. When you outgrow this, graduate to
[installation-production.md](installation-production.md); the
`.env` discipline and commands carry over unchanged.

This tutorial supersedes `deployment-1-server-dev.md`.
