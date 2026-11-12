from django.apps import AppConfig


class TonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.ton"
    label = "ton"
    verbose_name = "TON chain integration"
