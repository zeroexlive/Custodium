#!/usr/bin/env bash
# Maps a custodium-job@<name> instance to its management command.
# All worker commands are idempotent; overlapping runs are safe
# but wasteful, so the timers stagger them.
set -euo pipefail

cd /srv/custodium/apps/backend
UV=/home/custodium/.local/bin/uv

case "${1:-}" in
  process_withdrawals) exec "$UV" run python manage.py process_withdrawals ;;
  process_sweeps)      exec "$UV" run python manage.py process_sweeps ;;
  run_auto_sweeps)     exec "$UV" run python manage.py run_auto_sweeps ;;
  deliver_webhooks)    exec "$UV" run python manage.py deliver_webhooks ;;
  run_reconciliation)  exec "$UV" run python manage.py run_reconciliation ;;
  generate_invoices)   exec "$UV" run python manage.py generate_invoices ;;
  *)
    echo "unknown job: ${1:-<none>}" >&2
    exit 2
    ;;
esac
