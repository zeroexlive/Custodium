from django.apps import AppConfig
from django.core.checks import Warning, register


@register()
def sqlite_ledger_amount_warning(app_configs, **kwargs):  # noqa: ANN001, ANN202
    """SQLite cannot store DecimalField amounts exactly at wei scale.

    Django's SQLite backend adapts decimals through float, losing low
    bits for very large integers (raw sqlite3 INTEGER storage is exact;
    the ORM path is not). PostgreSQL NUMERIC(78,0) — the production
    database — is exact. Warn loudly so a SQLite deployment is never
    mistaken for a money-safe one.
    """
    from django.db import connection

    if connection.vendor == "sqlite":
        return [
            Warning(
                "Ledger amounts are NOT exact at wei scale on SQLite "
                "(Django adapts DecimalField via float). Use PostgreSQL "
                "for any ledger use beyond small-scale demos.",
                id="ledger.W001",
            )
        ]
    return []


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.ledger"
    label = "ledger"
