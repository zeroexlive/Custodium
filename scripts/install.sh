#!/usr/bin/env bash
# Custodium — interactive step-by-step installer (single-server DEV topology).
#
# What it does:
#   * checks prerequisites, asks before every major step
#   * installs either via Docker Compose (recommended) or natively (uv + SQLite)
#   * generates fresh secrets into .env (never overwrites without asking)
#   * runs migrations, seeds the network/asset registry and plan catalog
#   * optionally creates the first staff (superuser) account
#   * verifies the install via /healthz and /readyz
#
# This installs the DEVELOPMENT topology on ONE server. It is not a
# production deployment: see docs/operations/deployment-6-server.md and
# docs/architecture/phase-12-hardening.md (Custodium is NOT Production
# Approved; production signing is disabled pending independent review).
#
# Usage:
#   scripts/install.sh              interactive
#   scripts/install.sh --yes        accept defaults (still prints every step)
#   scripts/install.sh --dry-run    print every command, change nothing
set -euo pipefail

ASSUME_YES=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) grep '^#' "$0" | head -20; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------- helpers
c_step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
c_info() { printf '    %s\n' "$*"; }
c_warn() { printf '\033[1;33m    ! %s\033[0m\n' "$*"; }

confirm() {
  # confirm "question" — returns 0 on yes
  if [ "$ASSUME_YES" = "1" ]; then c_info "(--yes) $1 → yes"; return 0; fi
  local reply
  printf '    %s [y/N] ' "$1"
  read -r reply </dev/tty || reply=""
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

run() {
  # run CMD... — executes, or prints in dry-run mode
  if [ "$DRY_RUN" = "1" ]; then printf '    [dry-run] %s\n' "$*"; else "$@"; fi
}

have() { command -v "$1" >/dev/null 2>&1; }

rand_hex() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
fernet_key() {
  # A Fernet key is url-safe base64 of 32 bytes.
  head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'
}

# ---------------------------------------------------------------- intro
cat <<'BANNER'

  ██████╗██╗   ██╗███████╗████████╗ ██████╗ ██████╗ ██╗██╗   ██╗███╗   ███╗
 ██╔════╝██║   ██║██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗██║██║   ██║████╗ ████║
 ██║     ██║   ██║███████╗   ██║   ██║   ██║██║  ██║██║██║   ██║██╔████╔██║
 ██║     ██║   ██║╚════██║   ██║   ██║   ██║██║  ██║██║██║   ██║██║╚██╔╝██║
 ╚██████╗╚██████╔╝███████║   ██║   ╚██████╔╝██████╔╝██║╚██████╔╝██║ ╚═╝ ██║
  ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝ ╚═════╝ ╚═╝     ╚═╝
        Multi-chain MPC Wallet-as-a-Service — single-server DEV installer

BANNER
c_warn "Development topology on ONE server. NOT for real-value custody."
c_warn "Production needs the six-server topology + independent review gates."
confirm "Continue with the installation?" || { echo "Aborted."; exit 0; }

# ---------------------------------------------------------------- step 1: locate / fetch the code
c_step "Step 1/8 — Source code"
REPO_DIR=""
if [ -f "apps/backend/manage.py" ] && [ -f "docker-compose.yml" ]; then
  REPO_DIR="$(pwd)"
  c_info "Found a Custodium checkout here: $REPO_DIR"
else
  c_info "No checkout in the current directory."
  if confirm "Clone https://github.com/zeroexlive/Custodium.git into ./Custodium?"; then
    have git || { echo "git is required to clone." >&2; exit 1; }
    run git clone https://github.com/zeroexlive/Custodium.git Custodium
    REPO_DIR="$(pwd)/Custodium"
  else
    echo "Run this script from the repository root, or allow the clone." >&2
    exit 1
  fi
fi
cd "$REPO_DIR"

# ---------------------------------------------------------------- step 2: choose the install mode
c_step "Step 2/8 — Installation mode"
MODE=""
if have docker && docker compose version >/dev/null 2>&1; then
  c_info "Docker + Compose detected."
  if confirm "Use Docker Compose (recommended: PostgreSQL + Redis + Temporal + app)?"; then
    MODE="compose"
  fi
fi
if [ -z "$MODE" ]; then
  c_info "Native mode: Python 3.12 + uv, Node 20+, SQLite database."
  have python3 || { echo "python3 is required for native mode." >&2; exit 1; }
  if ! have uv; then
    if confirm "Install uv (https://astral.sh/uv)?"; then
      run bash -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
      export PATH="$HOME/.local/bin:$PATH"
    else
      echo "uv is required for native mode." >&2; exit 1
    fi
  fi
  have node || c_warn "Node.js not found — the dashboard step will be skipped."
  MODE="native"
fi
c_info "Mode: $MODE"

# ---------------------------------------------------------------- step 3: secrets / .env
c_step "Step 3/8 — Configuration (.env)"
if [ -f .env ]; then
  c_warn ".env already exists — it will NOT be overwritten."
else
  if confirm "Generate .env with fresh random secrets?"; then
    DJANGO_SECRET_KEY="$(rand_hex)$(rand_hex)"
    WAAS_KEY="$(fernet_key)"
    POSTGRES_PASSWORD="$(rand_hex)"
    if [ "$DRY_RUN" = "1" ]; then
      c_info "[dry-run] would write .env (DJANGO_SECRET_KEY, WAAS_SECRET_ENCRYPTION_KEY, POSTGRES_PASSWORD generated)"
    else
      cat > .env <<EOF
# Generated by scripts/install.sh — development only. Never commit this file.
DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY
DJANGO_ALLOWED_HOSTS=*
DJANGO_SETTINGS_MODULE=config.settings.development
DATABASE_URL=
REDIS_URL=redis://localhost:6379/0
WAAS_SECRET_ENCRYPTION_KEY=$WAAS_KEY
POSTGRES_DB=custodium
POSTGRES_USER=custodium
POSTGRES_PASSWORD=<redacted>
EOF
      chmod 600 .env
      c_info ".env written (chmod 600). Secrets were generated locally and are not printed."
    fi
  else
    c_info "Skipping .env generation — copy .env.example to .env and fill it in before continuing."
    confirm "Press y once your .env is ready" || exit 1
  fi
fi
if [ "$MODE" = "native" ] && [ -f .env ]; then
  # Native processes do not auto-load .env; export for this session's commands.
  set -a; # shellcheck disable=SC1091
  . ./.env; set +a
  c_info "Loaded .env into the installer session (native mode)."
fi

# ---------------------------------------------------------------- step 4: dependencies
c_step "Step 4/8 — Install dependencies"
if [ "$MODE" = "compose" ]; then
  c_info "Compose builds the backend and dashboard images; nothing to install on the host."
else
  confirm "Run 'uv sync --group dev' for the backend?" && run bash -c "cd apps/backend && uv sync --group dev"
  if have node && confirm "Run 'npm install' for the dashboard?"; then
    run bash -c "cd apps/dashboard && npm install"
  fi
fi

# ---------------------------------------------------------------- step 5: database + seeds
c_step "Step 5/8 — Database migrations and seed data"
if [ "$MODE" = "compose" ]; then
  confirm "Build and start the stack (docker compose up --build -d)?" || exit 1
  run docker compose up --build -d
  c_info "The backend container migrates + seeds the registry on start."
  if confirm "Also seed the plan catalog (seed_plans)?"; then
    run docker compose exec backend python manage.py seed_plans
  fi
else
  confirm "Run migrations?" && run bash -c "cd apps/backend && uv run python manage.py migrate"
  confirm "Seed networks + verified assets?" && run bash -c "cd apps/backend && uv run python manage.py seed_networks_assets"
  confirm "Seed the plan catalog?" && run bash -c "cd apps/backend && uv run python manage.py seed_plans"
fi

# ---------------------------------------------------------------- step 6: first staff account
c_step "Step 6/8 — First staff account (optional)"
c_info "A staff account can operate the platform halt and use Django admin."
if confirm "Create a superuser now?"; then
  if [ "$MODE" = "compose" ]; then
    run docker compose exec backend python manage.py createsuperuser
  else
    run bash -c "cd apps/backend && uv run python manage.py createsuperuser"
  fi
fi

# ---------------------------------------------------------------- step 7: start (native) / verify
c_step "Step 7/8 — Verify the installation"
if [ "$MODE" = "native" ]; then
  c_info "Starting the backend briefly to probe /healthz and /readyz…"
  if [ "$DRY_RUN" = "1" ]; then
    c_info "[dry-run] would start runserver, probe the endpoints, and stop it."
  else
    (cd apps/backend && uv run python manage.py runserver 127.0.0.1:8000 >/tmp/custodium-install.log 2>&1 &)
    sleep 2
  fi
fi
if [ "$DRY_RUN" = "1" ]; then
  c_info "[dry-run] would poll http://localhost:8000/healthz and /readyz until ready."
else
  ok=0
  for i in $(seq 1 30); do
    if curl -fsS localhost:8000/healthz >/dev/null 2>&1 && curl -fsS localhost:8000/readyz >/dev/null 2>&1; then
      ok=1; break
    fi
    sleep 2
  done
  if [ "$ok" = "1" ]; then
    c_info "healthz: $(curl -s localhost:8000/healthz)"
    c_info "readyz:  $(curl -s localhost:8000/readyz)"
  else
    c_warn "Probes did not answer within ~60s."
    [ "$MODE" = "compose" ] && c_warn "Check: docker compose logs backend"
    [ "$MODE" = "native" ] && c_warn "Check: /tmp/custodium-install.log"
  fi
  if [ "$MODE" = "native" ]; then
    pkill -f "manage.py runserver 127.0.0.1:8000" 2>/dev/null || true
    c_info "Probe server stopped. Start it for real with the commands below."
  fi
fi

# ---------------------------------------------------------------- step 8: summary
c_step "Step 8/8 — Done"
cat <<'EOF'
    ────────────────────────────────────────────────────────────────
    Dashboard   http://localhost:5173
    API         http://localhost:8000/api/v1/
    Health      http://localhost:8000/healthz · /readyz

    First steps (docs/operations/deployment-1-server-dev.md):
      1. Register a user in the dashboard, create an organization
         and a sandbox project.
      2. Issue an API key (secret shown once) and make a signed
         call — examples: docs/api/sdk-examples.md.
      3. Run the workers as needed:
           manage.py run_indexer --network ethereum
           manage.py process_withdrawals · process_sweeps
           manage.py deliver_webhooks · run_reconciliation

    Wallets will show 'provisioning' — address derivation and
    signing stay disabled until the independent MPC review.
    Production topology: docs/operations/deployment-6-server.md
    ────────────────────────────────────────────────────────────────
EOF
if [ "$MODE" = "compose" ]; then
  c_info "Stack is running under Docker Compose (docker compose ps)."
else
  c_info "Native mode — start the servers:"
  c_info "  cd apps/backend  && uv run python manage.py runserver"
  c_info "  cd apps/dashboard && npm run dev"
fi
echo
c_info "Installation finished."
