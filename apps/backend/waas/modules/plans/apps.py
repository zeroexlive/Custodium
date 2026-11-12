from django.apps import AppConfig


class PlansConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.plans"
    label = "plans"
    verbose_name = "Plans, quotas, usage & billing (fiat)"
