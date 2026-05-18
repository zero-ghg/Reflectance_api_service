from celery.schedules import crontab  # 导入 Celery 的 crontab 调度器

# Celery Beat 定时任务调度配置
CELERY_BEAT_SCHEDULE = {
    # 任务名称：雷电预警每6分钟执行一次
    "lightning-warning-every-6-minutes": {
        # 要执行的任务路径（模块.函数名）
        "task": "lightning_warning.celery_beat.tasks.run_lightning_warning_schedule_task",
        # 调度规则：每6分钟执行一次（在第0、6、12、18、24、30、36、42、48、54分钟触发）
        "schedule": crontab(minute="*/6"),
    },
}
