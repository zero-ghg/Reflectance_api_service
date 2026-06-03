from celery import shared_task

from reflectance.celery_beat.schedule_component import run_reflectance_schedule_once
from reflectance.celery_beat.precipitation_component import (
    run_precipitation_1h_schedule_once,
    run_precipitation_3h_schedule_once,
)


@shared_task(name="reflectance.celery_beat.tasks.run_reflectance_schedule_task")
def run_reflectance_schedule_task():
    """Celery Beat 定时调用入口：拉取最新雷达反射率并渲染落盘。"""
    print("[反射率] 定时任务开始执行 …", flush=True)
    run_reflectance_schedule_once()
    print("[反射率] 定时任务执行结束", flush=True)


# @shared_task(name="reflectance.celery_beat.tasks.run_precipitation_1h_schedule_task")
# def run_precipitation_1h_schedule_task():
#     """Celery Beat 定时调用入口：拉取 1 小时降水概率并渲染落盘。"""
#     print("[1小时降水概率] 定时任务开始执行 …", flush=True)
#     run_precipitation_1h_schedule_once()
#     print("[1小时降水概率] 定时任务执行结束", flush=True)
#
#
# @shared_task(name="reflectance.celery_beat.tasks.run_precipitation_3h_schedule_task")
# def run_precipitation_3h_schedule_task():
#     """Celery Beat 定时调用入口：拉取 3 小时降水概率并渲染落盘。"""
#     print("[3小时降水概率] 定时任务开始执行 …", flush=True)
#     run_precipitation_3h_schedule_once()
#     print("[3小时降水概率] 定时任务执行结束", flush=True)
