import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable


logger = logging.getLogger(__name__)


class IntervalAlignedScheduler:
    """
    对齐整点的固定间隔调度器。
    例如 interval_minutes=6 时，会在 xx:00/06/12/... 触发。
    """

    def __init__(self, name: str, interval_minutes: int, job: Callable[[], None]):
        self.name = name
        self.interval_minutes = max(int(interval_minutes), 1)
        self.job = job
        self._started = False
        self._lock = threading.Lock()

    def start(self):
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            worker = threading.Thread(target=self._run_loop, name=self.name, daemon=True)
            worker.start()
            self._started = True

    def _seconds_to_next_tick(self, now: datetime) -> float:
        aligned = now.replace(second=0, microsecond=0)
        minute_mod = aligned.minute % self.interval_minutes
        delta_minutes = self.interval_minutes - minute_mod
        if delta_minutes == 0:
            delta_minutes = self.interval_minutes
        next_tick = aligned + timedelta(minutes=delta_minutes)
        return max((next_tick - now).total_seconds(), 0.0)

    def _run_loop(self):
        while True:
            sleep_seconds = self._seconds_to_next_tick(datetime.now())
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            start_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {self.name} 开始执行"
            print(start_msg)
            logger.info(start_msg)
            try:
                self.job()
                end_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {self.name} 执行结束"
                print(end_msg)
                logger.info(end_msg)
            except Exception:
                logger.exception("调度任务执行失败: %s", self.name)
