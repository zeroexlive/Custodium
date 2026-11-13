"""Re-apply the Phase 12 append-only triggers after 0003.

Adding the `source` column remakes the snapshot table on
SQLite, which drops its database triggers; the trigger
installer is idempotent, so run it again after the alteration
(dependency on ledger 0003 guarantees the original install ran
first)."""

from django.db import migrations

from waas.common.db_triggers import (
    apply_append_only_triggers,
    remove_append_only_triggers,
)


class Migration(migrations.Migration):
    dependencies = [
        ("sweeps", "0003_static_destinations"),
        ("ledger", "0003_append_only_triggers"),
    ]

    operations = [
        migrations.RunPython(
            apply_append_only_triggers, migrations.RunPython.noop
        ),
    ]
