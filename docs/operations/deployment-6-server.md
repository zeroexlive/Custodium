# Tutorial — Six-Server Deployment (minimum production topology)

This tutorial deploys Custodium across **six servers**: the smallest
topology that preserves the platform's trust boundaries
(`docs/architecture/deployment-topology.md`,
`docs/architecture/trust-boundaries.md`). It implements Stage 1 of the
[rollout plan](mainnet-rollout-plan.md).

> **Scope and honesty.** This topology is *necessary but not sufficient*
> for production. Custodium remains **NOT Production Approved** until the
> gates in `docs/architecture/phase-12-hardening.md` close — above all
> the independent MPC review. The MPC signer binaries do not ship yet
> (the tier is fail-closed by design); Servers 4–6 below are provisioned
> and network-isolated now so the reviewed signer can be dropped in
> without re-architecting. Until then, wallets stay `provisioning` and
> no signing occurs.

## The six servers

| # | Role | Runs | Suggested size |
|---|---|---|---|
| S1 | **Application** | Django API (gunicorn), dashboard static build, reverse proxy (nginx) + TLS | 4 vCPU / 8 GB |
| S2 | **Workers + MPC coordinator** | Chain indexers, withdrawal/sweep processors, webhook delivery, reconciliation (scheduled commands); MPC coordinator/gateway on a private interface (it holds no shares — it only routes signing sessions) | 4 vCPU / 8 GB |
| S3 | **Data** | PostgreSQL 15+ (primary), Redis 7 | 4 vCPU / 16 GB / fast SSD |
| S4 | **MPC participant 1** | One key share (own operator domain) | 2 vCPU / 4 GB |
| S5 | **MPC participant 2** | One key share (own operator domain) | 2 vCPU / 4 GB |
| S6 | **MPC participant 3** | One key share (own operator domain) | 2 vCPU / 4 GB |

**Why the participants are three separate servers:** the threshold
is 2-of-3, and placement rule PL-2 requires each share on its own
host/failure domain. Never co-locate a participant with the API,
the database, another participant, or the coordinator's public
surface — one host compromise must never reach a signing quorum
(2 shares). If budget allows a 7th small host, give the coordinator
its own machine; it is the only role here that was consolidated for
count, and it holds no key material.

## Network layout

Three zones; only S1 is public.

| Zone | Members | Reachable from |
|---|---|---|
| Public edge | S1 (443 only) | Internet |
| App zone (private) | S1, S2, S3 | S1/S2 ↔ S3 on 5432/6379 only |
| Signing zone (isolated) | S4, S5, S6 (+ coordinator on S2) | Coordinator ↔ participants only; **no internet ingress, no route from S1/S3** |

Egress: S2 (and S1 for none) may reach chain RPC providers and tenant
resolver/webhook hosts over HTTPS. S4–S6 have **no general egress**.

## Step 0 — All servers

- Ubuntu 24.04 LTS (or equivalent), fully patched, automatic security
  updates on.
- A non-root deploy user `custodium` with key-only SSH; password auth
  disabled; firewall default-deny inbound.
- Time sync (chrony) — HMAC timestamps and MPC sessions depend on it.
- Clone the repo to `/srv/custodium`:
  `git clone https://github.com/zeroexlive/Custodium.git /srv/custodium`

## Step 1 — S3: data tier

```bash
# PostgreSQL 15+ and Redis 7 from your distro/vendor repos, then:
sudo -u postgres psql -c "CREATE USER custodium WITH PASSWORD '<strong>';"
sudo -u postgres psql -c "CREATE DATABASE custodium OWNER custodium;"
# postgresql.conf: listen only on the private interface; pg_hba.conf:
# allow S1/S2 private IPs only, scram-sha-256.
# redis.conf: bind private interface, requirepass <strong>, protected-mode yes.
```

Enable automated backups + point-in-time recovery **now**, and rehearse
a restore before any tenant data exists
(`docs/operations/disaster-recovery.md`).

Smoke test from S1/S2: `pg_isready -h <S3-private-ip>` and
`redis-cli -h <S3-private-ip> -a <pass> ping`.

## Step 2 — S1: application tier

```bash
cd /srv/custodium/apps/backend
curl -LsSf https://astral.sh/uv/install.sh | sh   # or your package route
uv sync --no-dev

cat > /srv/custodium/.env <<'EOF'
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=<50+ random chars>
DJANGO_ALLOWED_HOSTS=api.example.com
DATABASE_URL=postgres://custodium:<pass>@<S3-private-ip>:5432/custodium
REDIS_URL=redis://:<pass>@<S3-private-ip>:6379/0
WAAS_SECRET_ENCRYPTION_KEY=<Fernet key from your KMS/Vault — never a file in the repo>
EOF
chmod 600 /srv/custodium/.env

uv run python manage.py migrate
uv run python manage.py seed_networks_assets
uv run python manage.py seed_plans
uv run python manage.py createsuperuser   # first staff/operator account
```

The production settings **refuse to boot** with placeholder secrets —
that refusal is your configuration smoke test.

Run the API under systemd:

```ini
# /etc/systemd/system/custodium-api.service
[Unit]
After=network.target
[Service]
User=custodium
WorkingDirectory=/srv/custodium/apps/backend
EnvironmentFile=/srv/custodium/.env
ExecStart=/home/custodium/.local/bin/uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60
Restart=always
[Install]
WantedBy=multi-user.target
```

Dashboard + TLS on S1:

```bash
cd /srv/custodium/apps/dashboard && npm ci && npm run build   # → dist/
# nginx: serve dist/ statically; proxy /api/ and the probe paths to
# 127.0.0.1:8000; terminate TLS (Let's Encrypt or your CA).
```

Verify: `curl https://api.example.com/healthz` → `{"status":"ok"}`,
`/readyz` → `{"status":"ready"}`.

## Step 3 — S2: worker tier

Same checkout + `.env` as S1 (DATABASE_URL/REDIS_URL point at S3).
Workers are idempotent management commands; drive them with systemd
timers (or cron). One timer per job:

| Job | Command | Suggested cadence |
|---|---|---|
| EVM indexer | `manage.py run_indexer --network ethereum` (+ `--network bsc`) | every 15–30 s (loop service) |
| TRON indexer | `manage.py run_indexer --network tron` | every 15–30 s |
| Solana indexer | `manage.py run_indexer --network solana` | every 15–30 s |
| TON indexer | `manage.py run_indexer --network ton` | every 30–60 s |
| Withdrawals | `manage.py process_withdrawals` | every 15 s |
| Sweeps | `manage.py process_sweeps` | every 30 s |
| Webhooks | `manage.py deliver_webhooks` | every 30 s |
| Reconciliation | `manage.py run_reconciliation` | every 5–15 min — **any imbalance pages** |

Indexers are long-running loops in practice: wrap each in a systemd
service with `Restart=always` rather than a timer if your build's
command loops; both patterns are safe because every worker is
idempotent and resumes from stored cursors/state.

Also on S2 (private interface only): the **MPC coordinator/gateway**
process slot — provisioned, firewalled to reach S4–S6 only, activated
only after the review gate (Step 4).

## Step 4 — S4–S6: MPC participants (provisioning only, pre-review)

Per participant host, in its **own cloud account / failure domain**
where possible:

1. Harden per Step 0; **no inbound except from the coordinator**, no
   general internet egress.
2. Create the share-storage location per `key-ceremony.md` (encrypted
   store local to this domain; shares never leave it).
3. Stop here. The DKG ceremony, signer installation, and address
   registration happen **only** after the independent review closes,
   following `docs/operations/key-ceremony.md` exactly (3 share
   holders, witness, verified artifacts, transcript).

## Step 5 — Go-live checklist (Stage 1)

- [ ] `/healthz` + `/readyz` green behind the load path; halt endpoints
      tested: activate + deactivate the platform halt once
      (`POST /operator/platform-halt`, staff) and watch creation refuse.
- [ ] Reconciliation runs clean for every enabled network.
- [ ] Backups restored once on a scratch host (evidence, not intent).
- [ ] Withdrawal policies set conservatively (approvals ≥ 2, low caps)
      per tenant project.
- [ ] Sweep resolver endpoints registered by tenants over HTTPS and
      test-resolved from the console.
- [ ] RPC endpoints: at least two providers per network configured.
- [ ] Alerting wired: reconciliation breaks, scanner lag, webhook
      dead-letter growth, any halt activation.
- [ ] Rollout preconditions from `mainnet-rollout-plan.md` reviewed
      and signed off — including the item this topology cannot give
      you: the production approval decision.

## Scaling from here

Split order as load grows: S1 → 2 API replicas behind a managed LB;
S3 → add a read replica; S2 → one worker host per chain family;
coordinator → its own host. The MPC participant count **never**
changes for existing wallet groups — scaling signing is a security
decision, not an autoscaling event (topology doc §5).
