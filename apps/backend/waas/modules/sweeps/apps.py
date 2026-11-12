from django.apps import AppConfig


class SweepsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.sweeps"
    label = "sweeps"
    verbose_name = "Sweeps & treasury (resolver-endpoint destinations)"
