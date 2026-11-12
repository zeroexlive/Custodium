from django.apps import AppConfig


class SolanaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.solana"
    label = "solana"
    verbose_name = "Solana chain integration"
