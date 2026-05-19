"""Django 启动时自动拉起 Celery Worker + Beat（按 beat_schedule 定时执行，启动时不计算）。"""
import atexit
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_celery_procs: List[subprocess.Popen] = []  # 存储 Celery 子进程对象列表
_shutdown_registered = False  # 标记是否已注册关闭钩子
_stopping = False  # 标记是否正在停止进程中

# 不需要自动启动 Celery 的命令列表
_SKIP_COMMANDS = frozenset(
    {
        "shell",  # Django shell
        "test",  # 运行测试
        "check",  # 检查项目配置
        "collectstatic",  # 收集静态文件
        "createsuperuser",  # 创建超级用户
        "celery",  # Celery 命令
        "beat",  # Beat 命令
        "worker",  # Worker 命令
    }
)


def _project_root() -> Path:
    return Path(settings.BASE_DIR).resolve().parent  # 返回项目根目录路径


def should_auto_start_celery() -> bool:
    """判断是否应该自动启动 Celery。"""
    flag = str(getattr(settings, "CELERY_AUTO_START", "1")).lower()  # 获取自动启动配置标志
    if flag in ("0", "false", "no", "off"):  # 如果配置为禁用
        return False  # 不启动
    if os.environ.get("LIGHTNING_WARNING_CELERY_CHILD") == "1":  # 如果是 Celery 子进程
        return False  # 避免递归启动

    argv = sys.argv[1:]  # 获取命令行参数（排除脚本名）
    if not argv:  # 如果没有参数
        return False  # 不启动
    command = argv[0]  # 获取第一个参数（命令名）
    if command in _SKIP_COMMANDS:  # 如果是不需要 Celery 的命令
        return False  # 不启动

    if command == "runserver":  # 如果是 runserver 命令
        if "--noreload" in argv:  # 如果使用了 --noreload 参数
            return True  # 直接启动（不使用热重载）
        return os.environ.get("RUN_MAIN") == "true"  # 只在热重载的主进程中启动

    return False  # 其他情况不启动


def _popen(cmd: List[str], root: Path, env: dict) -> subprocess.Popen:
    """创建子进程，兼容 Windows 和 Linux。"""
    kwargs = {
        "cwd": str(root),  # 设置工作目录
        "env": env,  # 设置环境变量
        "stdout": None,  # 标准输出
        "stderr": None,  # 标准错误
    }
    if sys.platform == "win32":  # 如果是 Windows 系统
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # 创建新的进程组（便于管理）
    return subprocess.Popen(cmd, **kwargs)  # 创建并返回子进程对象


def _describe_beat_schedule(schedule) -> str:
    """将 Celery schedule 转为可读的中文描述。"""
    minute = getattr(schedule, "minute", None)
    if minute is not None and str(minute) in ("*/6", "{0,6,12,18,24,30,36,42,48,54}"):
        return "每 6 分钟（0、6、12… 分）"
    if isinstance(schedule, (int, float)):
        minutes = int(schedule) // 60
        return f"每 {minutes} 分钟" if minutes > 0 else f"每 {int(schedule)} 秒"
    return str(schedule)


# Beat 任务展示配置：仅打印定时规则、任务名称、结果入库
_BEAT_TASK_DISPLAY = {
    "lightning-warning-every-6-minutes": {
        "label": "雷电预警",
        "storage": "MySQL lightning_warning_result",
    },
    "reflectance-every-6-minutes": {
        "label": "反射率",
        "storage": "apps/img/radar_bin (bin) + apps/img/reflectance (PNG)",
    },
}


def _print_startup_info(
    worker_cmd: List[str], beat_cmd: List[str], worker_pid: int, beat_pid: int, node_name: str
) -> None:
    """打印 Celery 定时任务启动摘要（定时规则、任务名称、结果入库）。"""
    schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
    lines = ["", "=" * 60, "Celery 定时任务已启动", "=" * 60]

    for key, meta in _BEAT_TASK_DISPLAY.items():
        item = schedule.get(key)
        if not item:
            continue
        storage = meta["storage"]
        cron_desc = _describe_beat_schedule(item.get("schedule"))
        lines.extend(
            [
                f"[{meta['label']}]",
                f"  定时规则    : {cron_desc}",
                f"  任务名称    : {item.get('task', '')}",
                f"  结果入库    : {storage}",
                "",
            ]
        )

    lines.append("=" * 60)
    lines.append("")
    print("\n".join(lines), flush=True)


def _pid_file(name: str) -> Path:
    """获取 PID 文件路径。"""
    return _project_root() / f".celery_{name}.pid"  # 返回 .celery_worker.pid 或 .celery_beat.pid


def _kill_pid(pid: int) -> None:
    """强制终止指定 PID 的进程。"""
    try:
        if sys.platform == "win32":  # 如果是 Windows
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],  # 强制终止进程树
                stdout=subprocess.DEVNULL,  # 忽略输出
                stderr=subprocess.DEVNULL,  # 忽略错误
                check=False,  # 不检查返回值
            )
        else:  # 如果是 Linux/Mac
            os.kill(pid, signal.SIGTERM)  # 发送终止信号
    except (ProcessLookupError, OSError):  # 如果进程不存在
        pass  # 忽略错误


def _cleanup_stale_pid(name: str) -> None:
    """清理残留的 PID 文件和对应的进程。"""
    path = _pid_file(name)  # 获取 PID 文件路径
    if not path.is_file():  # 如果文件不存在
        return  # 直接返回
    try:
        _kill_pid(int(path.read_text(encoding="utf-8").strip()))  # 读取 PID 并终止进程
    except (ValueError, OSError):  # 如果读取失败
        pass  # 忽略错误
    try:
        path.unlink(missing_ok=True)  # 删除 PID 文件
    except OSError:  # 如果删除失败
        pass  # 忽略错误


def _save_pid(name: str, pid: int) -> None:
    """保存进程 PID 到文件。"""
    _pid_file(name).write_text(str(pid), encoding="utf-8")  # 将 PID 写入文件


def _clear_pid_files() -> None:
    """清除所有 PID 文件。"""
    for name in ("worker", "beat"):  # 遍历 worker 和 beat
        try:
            _pid_file(name).unlink(missing_ok=True)  # 删除 PID 文件
        except OSError:  # 如果删除失败
            pass  # 忽略错误


def _kill_process(proc: subprocess.Popen) -> None:
    """终止子进程。"""
    if proc.poll() is not None:  # 如果进程已经结束
        return  # 直接返回
    pid = proc.pid  # 获取进程ID
    try:
        if sys.platform == "win32":  # 如果是 Windows
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],  # 强制终止进程树
                stdout=subprocess.DEVNULL,  # 忽略输出
                stderr=subprocess.DEVNULL,  # 忽略错误
                check=False,  # 不检查返回值
            )
            proc.wait(timeout=5)  # 等待进程结束（最多5秒）
        else:  # 如果是 Linux/Mac
            proc.terminate()  # 发送终止信号
            proc.wait(timeout=10)  # 等待进程结束（最多10秒）
    except Exception:  # 如果终止失败
        try:
            proc.kill()  # 强制杀死进程
            proc.wait(timeout=5)  # 等待进程结束
        except Exception:  # 如果还是失败
            logger.exception("结束 Celery 子进程失败 pid=%s", pid)  # 记录错误日志


def _stop_celery() -> None:
    """停止所有 Celery 子进程。"""
    global _celery_procs, _stopping
    if _stopping:  # 如果已经在停止中
        return  # 避免重复执行
    _stopping = True  # 标记为停止中
    procs = _celery_procs  # 获取进程列表
    _celery_procs = []  # 清空列表
    for proc in procs:  # 遍历所有进程
        _kill_process(proc)  # 终止每个进程
    _clear_pid_files()  # 清除 PID 文件
    if procs:  # 如果有进程被终止
        print("[雷电预警] Celery Worker / Beat 已随项目结束而停止", flush=True)  # 打印提示信息
        logger.info("Celery 子进程已停止")  # 记录日志
    _stopping = False  # 重置停止标志


def _signal_handler(signum: int, frame: Optional[object]) -> None:
    """信号处理函数，用于优雅关闭。"""
    _stop_celery()  # 停止 Celery 进程


def _shutdown_legacy_workers() -> None:
    """结束仍使用默认节点名 celery@主机名 的遗留 Worker（避免 DuplicateNodenameWarning）。"""
    try:
        from Reflectance_api_service.celery import app  # 导入 Celery 应用

        legacy_node = f"celery@{socket.gethostname()}"  # 构建遗留节点名称
        app.control.broadcast("shutdown", destination=[legacy_node], timeout=3)  # 广播关闭命令
        print(f"[雷电预警] 已请求结束遗留 Worker: {legacy_node}", flush=True)  # 打印提示
        time.sleep(1)  # 等待1秒让进程关闭
    except Exception as exc:  # 如果失败
        logger.debug("结束遗留 Worker 跳过: %s", exc)  # 记录调试日志


def _register_shutdown_hooks() -> None:
    """注册进程关闭时的清理钩子。"""
    global _shutdown_registered
    if _shutdown_registered:  # 如果已经注册过
        return  # 避免重复注册
    _shutdown_registered = True  # 标记为已注册
    atexit.register(_stop_celery)  # 注册程序退出时的清理函数
    for sig in (signal.SIGINT, signal.SIGTERM):  # 遍历需要捕获的信号
        try:
            signal.signal(sig, _signal_handler)  # 注册信号处理函数
        except (ValueError, OSError):  # 如果注册失败
            pass  # 忽略错误
    if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):  # 如果是 Windows 且支持 SIGBREAK
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)  # 注册 Ctrl+Break 信号处理
        except (ValueError, OSError):  # 如果注册失败
            pass  # 忽略错误


def start_celery_with_django() -> None:
    """启动 Celery Worker 和 Beat 作为 Django 的子进程。"""
    global _celery_procs
    if _celery_procs and all(p.poll() is None for p in _celery_procs):  # 如果进程已在运行
        return  # 不重复启动

    root = _project_root()  # 获取项目根目录
    base = [sys.executable, "-m", "celery", "-A", "Reflectance_api_service"]  # 基础命令

    env = os.environ.copy()  # 复制当前环境变量
    env.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "Reflectance_api_service.settings.dev",  # 设置 Django 配置模块
    )
    env["LIGHTNING_WARNING_CELERY_CHILD"] = "1"  # 标记为 Celery 子进程（避免递归）
    apps_dir = root / "apps"  # apps 目录路径
    py_paths = [str(root)]  # Python 路径列表
    if apps_dir.is_dir():  # 如果 apps 目录存在
        py_paths.append(str(apps_dir))  # 添加到路径列表
    old_path = env.get("PYTHONPATH", "")  # 获取原有的 PYTHONPATH
    env["PYTHONPATH"] = os.pathsep.join(py_paths + ([old_path] if old_path else []))  # 合并路径

    _cleanup_stale_pid("worker")  # 清理残留的 worker PID
    _cleanup_stale_pid("beat")  # 清理残留的 beat PID
    _shutdown_legacy_workers()  # 关闭遗留的 Worker 进程

    node_name = f"lightning_warning.{os.getpid()}@%h"  # 构建唯一的节点名称（包含父进程ID）
    worker_cmd = base + ["worker", "-l", "info", "-n", node_name]  # Worker 启动命令
    if sys.platform == "win32":  # 如果是 Windows
        worker_cmd.extend(["--pool=solo"])  # 使用 solo 池（Windows 兼容）

    beat_schedule_file = root / ".celerybeat-schedule"  # Beat 调度文件路径
    beat_cmd = base + ["beat", "-l", "info", "--schedule", str(beat_schedule_file)]  # Beat 启动命令

    try:
        worker_proc = _popen(worker_cmd, root, env)  # 启动 Worker 进程
        beat_proc = _popen(beat_cmd, root, env)  # 启动 Beat 进程
        _celery_procs = [worker_proc, beat_proc]  # 保存进程对象
        _save_pid("worker", worker_proc.pid)  # 保存 Worker PID
        _save_pid("beat", beat_proc.pid)  # 保存 Beat PID
    except Exception:  # 如果启动失败
        logger.exception("启动 Celery 失败，请确认已安装 celery、Broker（如 Redis）已运行")  # 记录错误
        _stop_celery()  # 清理已启动的进程
        return  # 返回

    _register_shutdown_hooks()  # 注册关闭钩子
    _print_startup_info(worker_cmd, beat_cmd, worker_proc.pid, beat_proc.pid, node_name)  # 打印启动信息
    logger.info(
        "Celery Worker (pid=%s) + Beat (pid=%s) 已随 Django 启动",
        worker_proc.pid,  # Worker 进程ID
        beat_proc.pid,  # Beat 进程ID
    )


def try_start_celery_with_django() -> None:
    """尝试自动启动 Celery（根据配置和命令判断）。"""
    if should_auto_start_celery():  # 如果应该自动启动
        start_celery_with_django()  # 启动 Celery
