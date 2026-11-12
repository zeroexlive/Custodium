from django.apps import AppConfig


class EvmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.evm"
    label = "evm"
    verbose_name = "EVM chains (Ethereum & BSC)"
