from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.webhooks"
    label = "webhooks"
    verbose_name = "Webhooks (signed event delivery)"
