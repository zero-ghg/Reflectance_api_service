import logging
from datetime import timedelta
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from lightning_warning.models import LightningWarningResult

logger = logging.getLogger(__name__)

LOOKBACK_MINUTES = 10  # 数据回溯时间窗口（分钟），即计算最近10分钟的数据
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


def compute_and_save(calculator, query_dt) -> Tuple[List[Dict[str, Any]], str]:
    """
    以前端 time 为结束时刻，回溯 10 分钟计算并写入 MySQL。

    参数:
        calculator: Detail_Warning 实例，提供计算方法
        query_dt: 查询的时间点（naive datetime）

    返回:
        (预警数据列表, 响应时间字符串)
    """
    end_dt = query_dt  # 已经是 naive datetime
    start_dt = end_dt - timedelta(minutes=LOOKBACK_MINUTES)  # 计算开始时间（回溯10分钟）

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
    执行定时任务：计算当前时刻的雷电预警并保存到 MySQL。

    参数:
        calculator: Detail_Warning 实例
    """
    now_dt = timezone.now()  # 获取当前时间
    # 移除时区信息，转换为 naive datetime
    now_dt = now_dt.replace(tzinfo=None)

    end_dt = now_dt  # 结束时间为当前时间
    start_dt = end_dt - timedelta(minutes=LOOKBACK_MINUTES)  # 开始时间（回溯10分钟）

    # ... existing code ...

    # 打印计算窗口信息
    print(
        f"[雷电预警] 计算窗口: {calculator._format_api_time(start_dt)}"
        f" ~ {calculator._format_api_time(end_dt)}，读取 PostgreSQL t_atmo_data",
        flush=True,
    )

    # 构建预警列表（从 PostgreSQL 读取电场数据并计算）
    warning_list = calculator._build_warning_list(
        start_dt, end_dt, field_key="mesaure_value", unit="kV/m"
    )

    # 保存到 MySQL
    saved = _save_to_mysql(calculator, start_dt, end_dt, warning_list)

    # 格式化时间字符串
    end_str = calculator._format_api_time(end_dt)
    start_str = calculator._format_api_time(start_dt)

    # 构建日志消息
    msg = (
        f"lightning_warning 定时任务入库: response_time={end_str}, "
        f"rows={saved}, window=[{start_str},{end_str}]"
    )
    print(msg)  # 打印到控制台
    logger.info(msg)  # 记录到日志


def run_lightning_warning_schedule_once() -> None:
    """供 Celery task 调用：执行一次雷电预警定时计算。"""
    try:
        from lightning_warning.view.views import Detail_Warning  # 导入 Detail_Warning 类

        run_scheduled_job(Detail_Warning())  # 创建实例并执行定时任务
    except Exception:  # 捕获所有异常
        logger.exception("雷电预警定时任务执行失败")  # 记录异常日志
