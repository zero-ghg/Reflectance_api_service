from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "reflectance-every-6-minutes": {
        "task": "reflectance.celery_beat.tasks.run_reflectance_schedule_task",
        "schedule": crontab(minute="*/6"),
    },
}
