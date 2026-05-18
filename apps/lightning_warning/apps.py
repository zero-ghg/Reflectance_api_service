from django.apps import AppConfig


class WarningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lightning_warning"

    def ready(self):
        from lightning_warning.celery_runner import try_start_celery_with_django

        try_start_celery_with_django()
