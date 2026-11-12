from django.apps import AppConfig


class IndexingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "waas.modules.indexing"
    label = "indexing"
    verbose_name = "Chain indexing & deposit detection"
