"""Phase 12: DB-level append-only triggers for ledger, audit,
and sweep-snapshot tables (see waas/common/db_triggers.py)."""

from django.db import migrations

from waas.common.db_triggers import (
    apply_append_only_triggers,
    remove_append_only_triggers,
)


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0002_initial"),
        ("audit", "0002_initial"),
        ("sweeps", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            apply_append_only_triggers, remove_append_only_triggers
        ),
    ]
