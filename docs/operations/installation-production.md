# Installation Tutorial — Production

Deploy Custodium across **six servers**: the smallest topology
that preserves the platform's trust boundaries
(`docs/architecture/deployment-topology.md`,
`docs/architecture/trust-boundaries.md`), implementing Stage 1
of the [rollout plan](mainnet-rollout-plan.md). Ready-to-copy
unit/proxy/env files live under [`deploy/`](../../deploy).

> **Read this first — installation is not approval.** You can
> install everything in this tutorial today, rehearse on
> testnets, and run the full platform with the signer gate
> closed. **Custodium is NOT Production Approved.** Enabling
> the signer for real funds (Step 6) additionally requires:
> the independent cryptographic review passed, the penetration
> test closed, legal review, funded testnet soaks, the key
> ceremony executed per `key-ceremony.md`, and the written
> production approval decision. This tutorial marks every step
> that must wait for those gates.

## The six servers

| # | Role | Runs | Suggested size |
|---|---|---|---|
| S1 | Application | Django API (gunicorn), dashboard static build, nginx + TLS | 4 vCPU / 8 GB |
| S2 | Workers | Indexers, withdrawal/sweep processors, webhook delivery, reconciliation, invoicing (systemd services/timers) | 4 vCPU / 8 GB |
| S3 | Data | PostgreSQL 16/17, Redis 7 | 4 vCPU / 16 GB / fast SSD |
| S4 | Signer node 1 | `custodium-signer`, party 0 — own failure domain | 2 vCPU / 4 GB |
| S5 | Signer node 2 | `custodium-signer`, party 1 — own failure domain | 2 vCPU / 4 GB |
| S6 | Signer node 3 | `custodium-signer`, party 2 — own failure domain | 2 vCPU / 4 GB |

Threshold is **2-of-3**: each node holds one share on its own
host, ideally its own cloud account. Never co-locate a signer
node with the API, the database, or another signer node — one
host compromise must never reach a quorum. The backend talks to
**one** node's client API (any node can coordinate a ceremony);
the nodes talk **directly to each other** — there is no separate
coordinator process and no node ever sees another's share.

## Network layout

| Zone | Members | Reachable from |
|---|---|---|
| Public edge | S1 (443 only) | Internet |
| App zone (private) | S1, S2, S3 | S1/S2 ↔ S3 on 5432/6379 only |
| Signing zone (isolated) | S4, S5, S6 | Peers ↔ peers on 8401; client API (8401) from S1+S2 only; **no internet ingress** |

Egress: S1/S2 reach chain RPC providers and tenant
resolver/webhook hosts over HTTPS. S4–S6 need **no general
egress** (build the binary elsewhere and copy it in).

## Step 0 — All servers

- Ubuntu 24.04 LTS (or equivalent), patched, automatic security
  updates on.
- Non-root deploy user `custodium` (S4–S6: `custodium-signer`),
  key-only SSH, password auth disabled, firewall default-deny.
- Time sync (chrony) — HMAC timestamps and MPC sessions depend
  on it.
- Clone to `/srv/custodium`:
  `git clone https://github.com/zeroexlive/Custodium.git /srv/custodium`
  and check out your release tag.

## Step 1 — S3: data tier

```bash
# PostgreSQL 16/17 + Redis 7 from distro/vendor repos, then:
sudo -u postgres psql -c "CREATE USER custodium WITH PASSWORD '<strong>';"
sudo -u postgres psql -c "CREATE DATABASE custodium OWNER custodium;"
# postgresql.conf: listen on the private interface only.
# pg_hba.conf: S1/S2 private IPs only, scram-sha-256.
# redis.conf: bind private interface, requirepass <strong>, protected-mode yes.
```

Enable automated backups + point-in-time recovery **now**, and
rehearse a restore before any tenant data exists
(`docs/operations/disaster-recovery.md`).

Smoke test from S1/S2: `pg_isready -h <S3-ip>`,
`redis-cli -h <S3-ip> -a <pass> ping`.

## Step 2 — S1: application tier

```bash
cd /srv/custodium/apps/backend
curl -LsSf https://astral.sh/uv/install.sh | sh   # or your package route
uv sync --no-dev
cp /srv/custodium/deploy/env/backend.env.example /srv/custodium/.env
chmod 600 /srv/custodium/.env   # fill every <...> value; secrets via KMS/Vault
```

The signer-gate lines in `.env` stay **commented out** (gate
closed) until Step 6.

**RPC overlay.** Chain endpoints are Django settings (dicts per
network slug, ≥2 providers per network for failover). Create
`apps/backend/config/settings/local_production.py`:

```python
from .production import *  # noqa: F401,F403

EVM_RPC_ENDPOINTS = {
    "ethereum": ["https://provider-a.example/eth", "https://provider-b.example/eth"],
    "bsc": ["https://provider-a.example/bsc"],
    "ethereum-sepolia": ["https://provider-a.example/sepolia"],
    "bsc-testnet": ["https://provider-a.example/bsc-testnet"],
}
TRON_API_ENDPOINTS = {"tron": ["https://api.trongrid.io"], "tron-nile": ["https://nile.trongrid.io"]}
TRON_API_KEY = "..."           # if your provider requires one
SOLANA_RPC_ENDPOINTS = {"solana": ["https://provider.example/solana"], "solana-devnet": ["https://api.devnet.solana.com"]}
TON_API_ENDPOINTS = {"ton": ["https://toncenter.com/api/v2"], "ton-testnet": ["https://testnet.toncenter.com/api/v2"]}
TON_API_KEY = "..."
```

…and set `DJANGO_SETTINGS_MODULE=config.settings.local_production`
in `.env` on S1 **and** S2 (an identical overlay on both).

Initialize and serve:

```bash
uv run python manage.py migrate
uv run python manage.py seed_networks_assets
uv run python manage.py seed_plans
uv run python manage.py createsuperuser        # first staff/operator account

sudo cp /srv/custodium/deploy/systemd/custodium-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now custodium-api

cd /srv/custodium/apps/dashboard && npm ci && npm run build   # → dist/
sudo cp /srv/custodium/deploy/nginx/custodium.conf /etc/nginx/sites-available/custodium
sudo ln -s /etc/nginx/sites-available/custodium /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx   # + TLS certs (Let's Encrypt/your CA)
```

Production settings **refuse to boot** with placeholder secrets
— that refusal is your configuration smoke test. Verify:
`curl https://api.example.com/healthz` → `{"status":"ok"}`,
`/readyz` → `{"status":"ready"}`. Then register the first
tenant user, and **enable TOTP two-factor** on every operator
account (`docs/api/authentication.md` §6b).

## Step 3 — S2: worker tier

Same checkout, same `.env` + RPC overlay as S1. Install the job
machinery from `deploy/`:

```bash
sudo cp /srv/custodium/deploy/systemd/custodium-job@.service /etc/systemd/system/
sudo cp /srv/custodium/deploy/systemd/custodium-job@*.timer /etc/systemd/system/
sudo cp /srv/custodium/deploy/systemd/custodium-indexer@.service /etc/systemd/system/
sudo systemctl daemon-reload

# Periodic jobs (cadences ship in the timer files):
for j in process_withdrawals process_sweeps run_auto_sweeps deliver_webhooks run_reconciliation generate_invoices; do
  sudo systemctl enable --now custodium-job@$j.timer
done

# One indexer per network you serve (mainnet + testnet slugs):
for n in ethereum bsc tron solana ton; do
  sudo systemctl enable --now custodium-indexer@$n
done
```

| Job | Cadence | Notes |
|---|---|---|
| Indexers (`run_indexer --network <slug> --until-caught-up`) | continuous (restart loop) | deposit scanning per network |
| `process_withdrawals` | 15 s | dispatch + status refresh |
| `process_sweeps` | 30 s | resolve + execute |
| `run_auto_sweeps` | 1 min | threshold-triggered sweep creation |
| `deliver_webhooks` | 30 s | signed deliveries + retries |
| `run_reconciliation` | 10 min | **any imbalance pages** |
| `generate_invoices` | daily | plan invoicing (fiat, off-platform) |

Every worker is idempotent and resumes from stored state;
overlapping runs are safe.

## Step 4 — S4–S6: signer nodes

Build the binary on a build machine (or S4 before isolation),
never on a node from the network:

```bash
cd services/mpc && cargo build --release -p custodium-signer-service
# → target/release/custodium-signer; copy it to /usr/local/bin/ on S4, S5, S6
```

Per node (values differ per node — see
`deploy/env/signer-node.env.example`):

```bash
sudo useradd --system custodium-signer
sudo mkdir -p /var/lib/custodium-signer/store /etc/custodium
# The store key: 32 random bytes as 64 hex chars. Generate it ON
# this node; it must be unique per node and never leave the
# node's own custody except via the Step 5 backup procedure.
openssl rand -hex 32 | sudo tee /etc/custodium/store.key >/dev/null
sudo cp deploy/env/signer-node.env.example /etc/custodium/signer.env
# edit: SIGNER_PARTY_INDEX (0/1/2), SIGNER_PEERS (all three
# private addresses), tokens (shared across the cluster,
# generated once, stored in your secret manager)
sudo chown -R custodium-signer:custodium-signer /var/lib/custodium-signer /etc/custodium
sudo chmod 600 /etc/custodium/signer.env /etc/custodium/store.key
sudo cp deploy/systemd/custodium-signer.service /etc/systemd/system/
# add this node's IPAddressAllow lines for its two peers + S1/S2
sudo systemctl daemon-reload && sudo systemctl enable --now custodium-signer
curl localhost:8401/healthz
```

Cluster checks: each node's log shows it listening; from S1,
`curl -H "Authorization: Bearer <API token>" http://<any-node>:8401/v1/keys/nope`
returns 404 (auth + routing work; the key simply doesn't exist).
DKG ceremonies happen later, driven by wallet provisioning —
there is nothing else to "start".

**Transport note:** node-to-node traffic is authenticated with
the cluster token over HTTP inside the isolated zone. mTLS is
documented hardening that must land before real funds
(`docs/architecture/production-signer.md`, limitations) — the
signing zone's isolation is the compensating control until
then.

## Step 5 — Backups & disaster recovery

Two independent backup domains; losing either loses money
differently:

1. **Database (S3):** PITR + daily dumps, restore-rehearsed.
   Holds the ledger, wallets' public data, and the signer's
   key *references* — not shares.
2. **Signer stores (S4–S6):** per node, back up the **store
   directory and its store key file together**, encrypted, to
   media under *that participant domain's* custody. A store
   without its key (or vice versa) is unrecoverable **by
   design**; a quorum needs any 2 of 3 nodes' stores intact.
   Rehearse: restore one node onto a scratch host, restart it,
   and confirm it rejoins and can sign (testnet wallet).

Run both rehearsals before go-live and record the evidence
(`docs/operations/disaster-recovery.md`).

## Step 6 — Activation (GATED — do not skip the gates)

Only when **all** of these are true: independent review passed
· pentest closed · legal signed off · key ceremony executed
with witnesses per `key-ceremony.md` · this installation
rehearsed end-to-end on testnets with funded soaks ·
**written production approval recorded**.

1. In `/srv/custodium/.env` on S1+S2, set the signer gate:
   `MPC_SIGNER_ENABLED=true`, `MPC_SIGNER_URL=http://<one signer node's private IP>:8401`,
   `MPC_SIGNER_TOKEN=<redacted> (keep `MPC_SIGNER_THRESHOLD=2`).
2. Restart: workers first, then the API
   (`systemctl restart custodium-job@*.timer custodium-api` —
   practically: restart the job services' timers and the API).
3. Provision the first wallet (dashboard → wallet → Provision,
   or `manage.py provision_wallet <id>` on S2) and confirm the
   addresses on a block explorer.
4. Run a full testnet cycle per chain (deposit → credit →
   withdrawal → sweep) before any mainnet project is created.

If any gate is unmet, the correct production state is: platform
running, wallets `provisioning`, gate closed.

## Step 7 — Go-live checklist

- [ ] `/healthz` + `/readyz` green through nginx; TLS valid.
- [ ] Platform halt tested once (staff API): activation refuses
      wallet/withdrawal/sweep creation; deactivation restores.
- [ ] Reconciliation clean for every enabled network; alerting
      wired for imbalance, scanner lag, webhook dead letters,
      halt activation.
- [ ] TOTP 2FA enabled on all operator/staff accounts; API keys
      issued with scopes + IP allowlists + expiries.
- [ ] Withdrawal policies conservative at launch (quorum ≥ 2,
      low caps); address-book allowlist on for production
      projects.
- [ ] Tenant sweep resolver endpoints registered over HTTPS and
      test-resolved.
- [ ] ≥2 RPC providers per network; failover observed in logs.
- [ ] Backup restores rehearsed (DB + one signer node) with
      recorded evidence.
- [ ] Rollout preconditions in `mainnet-rollout-plan.md`
      reviewed; production approval decision signed.

## Upgrades & rollback

- Deploy in order: **S3 migrations are backward-compatible
  first** → run `migrate` from S1 → restart S2 jobs → restart
  S1 API → dashboard rebuild.
- **Signer nodes upgrade one at a time**, never during a
  ceremony, and never two at once (a 2-of-3 quorum must always
  be reachable). Verify `/healthz` + a testnet signature after
  each node.
- Rollback = previous release tag + the same restart order.
  Ledger and signer stores are append-only/forward-only: never
  roll back the database or a store directory to an older
  snapshot as a "fix" — restore procedures are in
  `disaster-recovery.md`, and they are rehearsed, not improvised.

This tutorial supersedes `deployment-6-server.md`.
