"""Phase 12: database-level append-only enforcement.

The model layer has blocked updates/deletes on append-only
tables since their introduction; this module installs the same
rule in the DATABASE so no code path — ORM misuse, raw SQL,
console access, a future service — can rewrite history.
Vendor-aware: PostgreSQL gets a shared trigger function,
SQLite (the test database) equivalent RAISE(ABORT) triggers.
"""

from __future__ import annotations

from django.db import connection

PG_FUNCTION = "custodium_forbid_change"

GUARDED_TABLES = {
    "ledger": ["ledger_journal_entry", "ledger_journal_line"],
    "audit": ["audit_audit_event"],
    "sweeps": ["sweeps_resolveddestinationsnapshot"],
}


def _trigger_names(table: str) -> tuple[str, str]:
    return (f"{table}_no_update", f"{table}_no_delete")


def apply_append_only_triggers(apps, schema_editor) -> None:
    vendor = connection.vendor
    tables = [table for group in GUARDED_TABLES.values() for table in group]
    with connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(
                f"""
                CREATE OR REPLACE FUNCTION {PG_FUNCTION}() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'append-only table: % changes are forbidden',
                        TG_TABLE_NAME;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            for table in tables:
                for action, timing in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                    cursor.execute(
                        f"DROP TRIGGER IF EXISTS {table}_{timing} ON {table}"
                    )
                    cursor.execute(
                        f"CREATE TRIGGER {table}_{timing} BEFORE {action} ON {table} "
                        f"FOR EACH ROW EXECUTE FUNCTION {PG_FUNCTION}()"
                    )
        elif vendor == "sqlite":
            for table in tables:
                for action, timing in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                    cursor.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{timing} "
                        f"BEFORE {action} ON {table} "
                        f"BEGIN SELECT RAISE(ABORT, 'append-only table: {table}'); END"
                    )
        # Other vendors: model-layer enforcement still applies;
        # production is PostgreSQL-only (settings guard).


def remove_append_only_triggers(apps, schema_editor) -> None:
    vendor = connection.vendor
    tables = [table for group in GUARDED_TABLES.values() for table in group]
    with connection.cursor() as cursor:
        if vendor == "postgresql":
            for table in tables:
                for timing in ("no_update", "no_delete"):
                    cursor.execute(f"DROP TRIGGER IF EXISTS {table}_{timing} ON {table}")
            cursor.execute(f"DROP FUNCTION IF EXISTS {PG_FUNCTION}()")
        elif vendor == "sqlite":
            for table in tables:
                for timing in ("no_update", "no_delete"):
                    cursor.execute(f"DROP TRIGGER IF EXISTS {table}_{timing}")
