import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Reflectance_api_service.settings.dev")

app = Celery("Reflectance_api_service")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
# 定时任务放在 lightning_warning/celery_beat/ 子包内
app.autodiscover_tasks(["lightning_warning.celery_beat"])
