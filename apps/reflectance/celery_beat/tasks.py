from celery import shared_task

from reflectance.celery_beat.schedule_component import run_reflectance_schedule_once


@shared_task(name="reflectance.celery_beat.tasks.run_reflectance_schedule_task")
def run_reflectance_schedule_task():
    """Celery Beat 定时调用入口：拉取最新雷达反射率并渲染落盘。"""
    print("[反射率] 定时任务开始执行 …", flush=True)
    run_reflectance_schedule_once()
    print("[反射率] 定时任务执行结束", flush=True)
