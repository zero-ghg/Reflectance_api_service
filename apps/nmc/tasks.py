import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from celery import shared_task
from django.db import transaction

from apps.nmc.models import WeatherWarning

# 这里改成你实际写接口调用方法的位置
# 例如：from nmc.services.music import query_warning_records
from apps.nmc.music import query_warning_records


logger = logging.getLogger(__name__)


def clean_str(value: Any) -> Optional[str]:
    """
    清洗字符串：
    - None -> None
    - "" -> None
    - "null" -> None
    - 其他 -> 去除前后空格后的字符串
    """
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    if value.lower() == "null":
        return None

    return value


def parse_datetime(value: Any) -> Optional[datetime]:
    """
    解析接口时间字段。
    支持：
    - 2026-05-01 18:07:24
    - 2026/05/01 18:07:24
    - 20260501180724
    """
    value = clean_str(value)

    if not value:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y%m%d%H%M%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    logger.warning("时间格式无法解析: %s", value)
    return None


# 新增: 统一整理接口返回的预警记录
def normalize_records(raw_records: Any) -> List[Dict[str, Any]]:
    """
    将接口返回结果统一整理成预警记录列表。

    兼容以下几种返回：
    - [{...}, {...}]
    - {"DS": [{...}, {...}]}
    - {"data": {"DS": [{...}, {...}]}}
    - {"result": {"DS": [{...}, {...}]}}
    """
    if raw_records is None:
        return []

    # 如果接口方法返回的是 JSON 字符串，先解析成 dict
    if isinstance(raw_records, str):
        import json
        try:
            raw_records = json.loads(raw_records)
        except json.JSONDecodeError:
            logger.warning("接口返回字符串不是合法 JSON: %s", raw_records[:500])
            return []

    if isinstance(raw_records, list):
        return [item for item in raw_records if isinstance(item, dict)]

    if isinstance(raw_records, dict):
        ds = raw_records.get("DS")
        if isinstance(ds, list):
            return [item for item in ds if isinstance(item, dict)]

        data = raw_records.get("data")
        if isinstance(data, dict):
            ds = data.get("DS")
            if isinstance(ds, list):
                return [item for item in ds if isinstance(item, dict)]

        result = raw_records.get("result")
        if isinstance(result, dict):
            ds = result.get("DS")
            if isinstance(ds, list):
                return [item for item in ds if isinstance(item, dict)]

    logger.warning("接口返回结构不是预期的记录列表: type=%s, value=%s", type(raw_records), raw_records)
    return []


def build_warning_data(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    将接口字段清洗成 WeatherWarning 模型字段。
    """
    if not isinstance(item, dict):
        logger.warning("跳过非字典预警数据: %s", item)
        return None
    warning_id = clean_str(item.get("ID"))

    if not warning_id:
        logger.warning("跳过无 ID 的预警数据: %s", item)
        return None

    signal_type = clean_str(item.get("SIGNAL_TYPE"))

    return {
        "warning_id": warning_id,
        "publish_id": clean_str(item.get("PUBLISH_ID")),
        "pid": clean_str(item.get("PID")),
        "warn_code": clean_str(item.get("WARN_CODE")),

        "iymdhm": parse_datetime(item.get("IYMDHM")),
        "rymdhm": parse_datetime(item.get("RYMDHM")),

        "warn_time": parse_datetime(item.get("WARN_TIME")),
        "warn_period": clean_str(item.get("WARN_PERIOD")),

        "warn_type": clean_str(item.get("WARN_TYPE")),
        "warn_level": clean_str(item.get("WARN_LEVEL")),

        "signal_type": signal_type,
        "is_active": False if signal_type == "2" else True,

        "warn_content": clean_str(item.get("WARN_CONTENT")),
        "warn_area": clean_str(item.get("WARN_AREA")),
        "warn_measure": clean_str(item.get("WARN_MEASURE")),

        "area_code": clean_str(item.get("AREA_CODE")),
        "publish_unit": clean_str(item.get("PUBLISH_UNIT")),
        "status": clean_str(item.get("STATUS")),

        "make_time": parse_datetime(item.get("MAKE_TIME")),

        "raw_json": item,
    }


def save_one_warning(item: Dict[str, Any]) -> str:
    """
    保存单条预警。
    根据 warning_id 去重。

    返回：
    - created
    - updated
    - skipped
    """
    data = build_warning_data(item)

    if not data:
        return "skipped"

    warning_id = data.pop("warning_id")

    obj, created = WeatherWarning.objects.update_or_create(
        warning_id=warning_id,
        defaults=data,
    )

    # 如果当前记录是解除信号，根据信号 PID 把原始预警也置为已解除。
    #
    # 例如：
    # 当前解除记录：
    # ID = 59127
    # PID = 59114
    # SIGNAL_TYPE = 2
    #
    # 那么需要把 warning_id = 59114 的原始预警设置为 is_active=False
    if obj.signal_type == "2" and obj.pid:
        WeatherWarning.objects.filter(
            warning_id=obj.pid
        ).update(
            is_active=False
        )

        # 同时，如果有变更记录也使用同一个 PID，也可以一起置为解除
        WeatherWarning.objects.filter(
            pid=obj.pid
        ).update(
            is_active=False
        )

    return "created" if created else "updated"


@shared_task(name="nmc.tasks.sync_weather_warning_task")
def sync_weather_warning_task():
    """
    定时同步天气预警数据。

    逻辑：
    1. 调用预警接口
    2. 清洗字段
    3. 根据 ID 去重保存
    4. 如果 SIGNAL_TYPE=2，解除原始预警
    """
    logger.info("开始同步天气预警数据")

    try:
        raw_records = query_warning_records()
        records = normalize_records(raw_records)
        logger.info(
            "预警接口返回类型 raw_type=%s, records_type=%s, records_count=%s",
            type(raw_records).__name__,
            type(records).__name__,
            len(records) if isinstance(records, list) else "not-list",
        )
    except Exception as e:
        logger.exception("调用天气预警接口失败: %s", e)
        return {
            "success": False,
            "message": f"调用天气预警接口失败: {e}",
        }

    # 双保险：如果 records 仍然不是 list，说明接口返回结构未被正确展开，这里再展开一次
    if not isinstance(records, list):
        records = normalize_records(records)

    if not records:
        logger.info("本次没有获取到天气预警数据")
        return {
            "success": True,
            "total": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
        }

    created_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = 0

    # 再次防止 dict 被直接遍历成 returnCode、DS 等 key
    if isinstance(records, dict):
        records = normalize_records(records)

    with transaction.atomic():
        for item in records:
            if not isinstance(item, dict):
                skipped_count += 1
                logger.warning("跳过非字典预警数据: %s", item)
                continue
            try:
                result = save_one_warning(item)

                if result == "created":
                    created_count += 1
                elif result == "updated":
                    updated_count += 1
                else:
                    skipped_count += 1

            except Exception as e:
                error_count += 1
                logger.exception("保存单条预警失败: %s, item=%s", e, item)

    logger.info(
        "天气预警同步完成 total=%s created=%s updated=%s skipped=%s error=%s",
        len(records),
        created_count,
        updated_count,
        skipped_count,
        error_count,
    )

    return {
        "success": True,
        "total": len(records),
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "error": error_count,
    }