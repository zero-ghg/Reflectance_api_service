import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Reflectance_api_service.settings.dev')

from celery import Celery

app = Celery('Reflectance_api_service')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()