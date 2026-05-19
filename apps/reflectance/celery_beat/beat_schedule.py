from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "reflectance-every-6-minutes": {
        "task": "reflectance.celery_beat.tasks.run_reflectance_schedule_task",
        "schedule": crontab(minute="1-59/6"),
    },
    "precipitation-1h-every-6-minutes": {
        "task": "reflectance.celery_beat.tasks.run_precipitation_1h_schedule_task",
        "schedule": crontab(minute="1-59/6"),
    },
    "precipitation-3h-hourly": {
        "task": "reflectance.celery_beat.tasks.run_precipitation_3h_schedule_task",
        "schedule": crontab(minute="1"),
    },
}
