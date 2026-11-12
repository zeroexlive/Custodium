from django.apps import AppConfig


class OperationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.operations"
    label = "operations"
    verbose_name = "Financial operations (withdrawals, policy, reconciliation)"
