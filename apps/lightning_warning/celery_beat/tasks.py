from celery import shared_task

from lightning_warning.celery_beat.schedule_component import run_lightning_warning_schedule_once


@shared_task(name="lightning_warning.celery_beat.tasks.run_lightning_warning_schedule_task")
def run_lightning_warning_schedule_task():
    """Celery Beat 定时调用入口：执行一次雷电预警计算并落库。"""
    print("[雷电预警] 定时任务开始执行 …", flush=True)
    run_lightning_warning_schedule_once()
    print("[雷电预警] 定时任务执行结束", flush=True)
