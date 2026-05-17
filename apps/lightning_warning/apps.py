from django.apps import AppConfig
import os
import sys
import logging


logger = logging.getLogger(__name__)


class WarningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lightning_warning"
    _scheduler = None

    def ready(self):
        # 避免在迁移/测试等管理命令下启动后台调度线程。
        skip_commands = {"makemigrations", "migrate", "collectstatic", "shell", "test"}
        if any(cmd in sys.argv for cmd in skip_commands):
            return

        # runserver 自动重载会启动两次，子进程（RUN_MAIN=true）才启动任务。
        # 但 runserver --noreload 没有子进程，此时也应允许启动。
        if (
            "runserver" in sys.argv
            and "--noreload" not in sys.argv
            and os.environ.get("RUN_MAIN") != "true"
        ):
            return

        from lightning_warning.scheduler import IntervalAlignedScheduler
        from lightning_warning.view.views import run_lightning_warning_schedule_once

        if self.__class__._scheduler is None:
            self.__class__._scheduler = IntervalAlignedScheduler(
                name="lightning-warning-scheduler",
                interval_minutes=6,
                job=run_lightning_warning_schedule_once,
            )
        self.__class__._scheduler.start()
        msg = "lightning_warning 定时任务已启动：从整点开始，每6分钟执行一次"
        print(msg)
        logger.info(msg)
