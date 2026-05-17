import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / 'apps'))  # 和 manage.py 保持完全一致

from .celery import app as celery_app
__all__ = ('celery_app',)