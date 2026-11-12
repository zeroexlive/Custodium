from django.apps import AppConfig


class TronConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.tron"
    label = "tron"
    verbose_name = "TRON chain integration"
