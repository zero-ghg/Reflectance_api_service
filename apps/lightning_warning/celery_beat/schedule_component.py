import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from lightning_warning.models import LightningWarningResult

logger = logging.getLogger(__name__)

LOOKBACK_MINUTES = int(os.getenv("LIGHTNING_WARNING_LOOKBACK_MINUTES", "30"))
CACHE_LOOKAROUND_MINUTES = int(os.getenv("LIGHTNING_WARNING_CACHE_LOOKAROUND_MINUTES", "60"))
MYSQL_DB = "default"  # MySQL 数据库别名（对应 settings.DATABASES 中的 'mysql'）


def _save_to_mysql(calculator, start_dt, end_dt, warning_list: List[Dict[str, Any]]) -> int:
    """将预警结果批量保存到 MySQL 数据库。"""
    if not warning_list:  # 如果预警列表为空
        return 0  # 返回0

    # 构建模型对象列表
    objs = [
        LightningWarningResult(
            start_time=start_dt,  # 开始时间
            end_time=end_dt,  # 结束时间
            response_time=end_dt,  # 响应时间（使用结束时间）
            device_id=int(row["device_id"]),  # 设备ID
            device_name=str(row.get("device_name", "")),
            lng=row.get("lng"),
            lat=row.get("lat"),
            warning_type=int(row["type"]),  # 预警类型/等级
            max_val=int(row["max_val"]),  # 最大值
            min_val=int(row["min_val"]),  # 最小值
            avg_val=int(row["avg_val"]),  # 平均值
        )
        for row in warning_list  # 遍历预警列表中的每个设备数据
    ]
    LightningWarningResult.objects.using(MYSQL_DB).bulk_create(objs)  # 批量插入到 MySQL
    return len(objs)  # 返回保存的记录数


def _rows_to_api(qs) -> List[Dict[str, Any]]:
    """将数据库查询结果转换为 API 响应格式。"""
    return [
        {
            "device_id": int(row.device_id),  # 设备ID
            "device_name": row.device_name or "",
            "lng": row.lng,
            "lat": row.lat,
            "type": int(row.warning_type),  # 预警类型
            "max_val": int(row.max_val),  # 最大值
            "min_val": int(row.min_val),  # 最小值
            "avg_val": int(row.avg_val),  # 平均值
        }
        for row in qs  # 遍历查询结果集
    ]


def query_by_time(calculator, query_dt) -> Tuple[List[Dict[str, Any]], str]:
    """
    按时间查询已计算的预警结果。

    参数:
        calculator: Detail_Warning 实例
        query_dt: 查询的时间点（naive datetime）

    返回:
        (预警数据列表, 响应时间字符串)，如果没有数据则返回 ([], "")
    """
    end_dt = query_dt  # 已经是 naive datetime，直接使用
    # 从 MySQL 查询指定 response_time 的预警数据
    qs = (
        LightningWarningResult.objects.using(MYSQL_DB)
        .filter(response_time=end_dt)  # 精确匹配响应时间
        .order_by("device_id")  # 按设备ID排序
    )
    if not qs.exists():  # 如果没有找到数据
        return [], ""  # 返回空结果
    # 返回格式化后的数据和响应时间字符串
    return _rows_to_api(qs), calculator._format_api_time(end_dt)


def query_nearest_by_time(calculator, query_dt) -> Tuple[List[Dict[str, Any]], str, Optional[Any]]:
    """
    查询 query_dt 前后指定时间范围内最近的一批预警结果。

    返回:
        (预警数据列表, 响应时间字符串, 命中的 response_time)
    """
    start_dt = query_dt - timedelta(minutes=CACHE_LOOKAROUND_MINUTES)
    end_dt = query_dt + timedelta(minutes=CACHE_LOOKAROUND_MINUTES)
    rows = list(
        LightningWarningResult.objects.using(MYSQL_DB)
        .filter(response_time__gte=start_dt, response_time__lte=end_dt)
        .values("response_time")
        .distinct()
    )
    if not rows:
        return [], "", None

    nearest_dt = min(rows, key=lambda row: abs(row["response_time"] - query_dt))["response_time"]
    qs = (
        LightningWarningResult.objects.using(MYSQL_DB)
        .filter(response_time=nearest_dt)
        .order_by("device_id")
    )
    return _rows_to_api(qs), calculator._format_api_time(nearest_dt), nearest_dt


def compute_and_save(calculator, query_dt) -> Tuple[List[Dict[str, Any]], str]:
    """
    以前端 time 为结束时刻，按配置的分钟数回溯计算并写入 MySQL。

    参数:
        calculator: Detail_Warning 实例，提供计算方法
        query_dt: 查询的时间点（naive datetime）

    返回:
        (预警数据列表, 响应时间字符串)
    """
    end_dt = query_dt  # 已经是 naive datetime
    start_dt = end_dt - timedelta(minutes=LOOKBACK_MINUTES)

    # 调用 Detail_Warning 的方法构建预警列表
    warning_list = calculator._build_warning_list(
        start_dt, end_dt, field_key="mesaure_value", unit="kV/m"
    )

    # 删除同一 response_time 的旧数据（避免重复）
    LightningWarningResult.objects.using(MYSQL_DB).filter(response_time=end_dt).delete()

    # 保存新计算的预警数据到 MySQL
    _save_to_mysql(calculator, start_dt, end_dt, warning_list)

    # 查询刚保存的数据并返回
    qs = (
        LightningWarningResult.objects.using(MYSQL_DB)
        .filter(response_time=end_dt)  # 查询刚才保存的数据
        .order_by("device_id")  # 按设备ID排序
    )
    return _rows_to_api(qs), calculator._format_api_time(end_dt)  # 返回格式化数据和时间字符串


def run_scheduled_job(calculator) -> None:
    """
    执行定时任务：取当前时刻，在 PG 中找最近监测时次作为 end_time，
    再向前回溯配置的分钟数计算并写入 MySQL。
    """
    now_dt = timezone.now().replace(tzinfo=None)

    end_dt = calculator._find_nearest_pg_end_time_before(now_dt)
    if end_dt is None:
        logger.warning("PostgreSQL 中无可用监测数据，雷电预警定时任务跳过")
        return

    start_dt = end_dt - timedelta(minutes=LOOKBACK_MINUTES)
    print(
        f"[雷电预警] 定时任务: now={calculator._format_api_time(now_dt)}, "
        f"PG最近时次 end_time={calculator._format_api_time(end_dt)}, "
        f"窗口=[{calculator._format_api_time(start_dt)}, {calculator._format_api_time(end_dt)}]",
        flush=True,
    )

    warning_list, resp_time = compute_and_save(calculator, end_dt)
    msg = (
        f"lightning_warning 定时任务入库: response_time={resp_time}, "
        f"rows={len(warning_list)}, "
        f"window=[{calculator._format_api_time(start_dt)},{calculator._format_api_time(end_dt)}]"
    )
    print(msg, flush=True)
    logger.info(msg)


def run_lightning_warning_schedule_once() -> None:
    """供 Celery task 调用：执行一次雷电预警定时计算。"""
    try:
        from lightning_warning.view.views import Detail_Warning  # 导入 Detail_Warning 类

        run_scheduled_job(Detail_Warning())  # 创建实例并执行定时任务
    except Exception:  # 捕获所有异常
        logger.exception("雷电预警定时任务执行失败")  # 记录异常日志
