import sys
import tempfile
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import re
import json

# 配置 MUSIC SDK 的源码路径，将其添加到 Python 模块搜索路径中
_SRC = Path(__file__).resolve().parent.parent.parent / "Reflectance_api_service" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ==================== MUSIC 平台配置 ====================
# MUSIC 客户端配置文件路径
MUSIC_CLIENT_CONFIG = _SRC / "demo" / "client.config"
# MUSIC 平台认证用户ID
MUSIC_USER_ID = "BETJ_FLZX_LI_YUN_BO"
# MUSIC 平台认证密码
MUSIC_PASSWORD = "Zhfymqm672!@$"
# MUSIC 接口ID：根据时间范围查询天气预警信号
MUSIC_INTERFACE_ID = "getSevpEleByTimeRange"
# MUSIC 天气预警接口默认参数
MUSIC_WARNING_ELEMENTS = (
    "IYMDHM,RYMDHM,"
    "PUBLISH_ID,ID,PID,WARN_CODE,WARN_TIME,WARN_PERIOD,"
    "WARN_TYPE,WARN_LEVEL,SIGNAL_TYPE,WARN_CONTENT,WARN_AREA,"
    "WARN_MEASURE,AREA_CODE,PUBLISH_UNIT,STATUS,"
    "MAKE_TIME"
)
MUSIC_RADAR_DEFAULT_PARAMS = {
    "dataCode": "SEVP_BETJ_TIPTOP_YJXH",  # 资料代码：天津天气预警信号
    "dataFormat": "json",  # 返回数据格式
    "elements": MUSIC_WARNING_ELEMENTS,  # 要素字段代码
    "limitCnt": "100",  # 最大返回记录数
}
# MUSIC 默认查询回溯时长（小时）：未指定 time 时，按格林威治时间从当前时刻向前查询
MUSIC_DEFAULT_LOOKBACK_HOURS = 2
# MUSIC 文件时次是否为 UTC（格林威治时间）
MUSIC_FILE_TIME_IS_UTC = True
# 本地业务时区相对 UTC 的偏移小时（北京时间 +8）
LOCAL_TIME_OFFSET_HOURS = 8

from Reflectance_api_service.src.cma.music.DataQueryClient import DataQueryClient


def _get_client():
    """
    创建并返回 MUSIC 数据查询客户端实例

    Returns:
        DataQueryClient: MUSIC 数据查询客户端对象

    Raises:
        FileNotFoundError: 当 client.config 配置文件不存在时抛出
    """
    config_file = Path(MUSIC_CLIENT_CONFIG)
    if not config_file.is_file():
        raise FileNotFoundError(f"未找到 client.config: {config_file}")
    return DataQueryClient(configFile=str(config_file))


def _parse_front_time(time_param: str) -> datetime:
    """
    解析前端传入的时间参数，支持多种时间格式

    Args:
        time_param: 时间字符串，支持以下格式：
            - YYYYMMDDHHmmss (如 20260515120100)
            - YYYY-MM-DD HH:MM:SS (如 2026-05-15 12:01:00)
            - YYYY-MM-DD HH:MM (如 2026-05-15 12:01)
            - ISO8601 格式 (如 2026-05-15T12:01:00)

    Returns:
        datetime: 解析后的 datetime 对象

    Raises:
        ValueError: 当时间格式不支持时抛出异常
    """
    target_text = str(time_param).strip()
    # 尝试匹配常见的时间格式
    for fmt in (
            "%Y%m%d%H%M%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.strptime(target_text, fmt)
        except ValueError:
            continue
    # 尝试 ISO8601 格式解析
    try:
        return datetime.fromisoformat(target_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "time 参数格式错误，支持 YYYYMMDDHHmmss 或 ISO8601（如 2026-05-15T12:01:00）"
        ) from exc


def _calculate_day_bounds(time_param=None):
    """
    根据前端传入时间计算当天的起止时刻

    Args:
        time_param: 可选的时间参数，如果未提供则使用当前时间

    Returns:
        tuple: (start_dt, end_dt) 当天的起始和结束时刻
            - start_dt: 当天 00:00:00
            - end_dt: 当天 23:59:59
    """
    if time_param:
        base_dt = _parse_front_time(time_param)
    else:
        base_dt = datetime.now()

    # 去除时区信息，统一使用本地时间
    base_dt = base_dt.replace(tzinfo=None)
    # 计算当天零点
    start_dt = base_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    # 计算当天最后一秒
    end_dt = base_dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return start_dt, end_dt


def _format_music_time(dt_obj: datetime) -> str:
    """
    将 datetime 对象格式化为 MUSIC 平台要求的时间格式

    Args:
        dt_obj: datetime 对象

    Returns:
        str: 格式化后的时间字符串 (YYYYMMDDHHMMSS)
    """
    return dt_obj.strftime("%Y%m%d%H%M%S")


def _normalize_file_time(dt_obj: datetime) -> datetime:
    """
    将 MUSIC 文件时次归一化到本地业务时间。
    当前平台返回为 UTC 时，统一加 8 小时转换为北京时间。
    """
    if MUSIC_FILE_TIME_IS_UTC:
        return dt_obj + timedelta(hours=LOCAL_TIME_OFFSET_HOURS)
    return dt_obj


def _iter_segment_ranges(day_start: datetime, day_end: datetime, segment_minutes: int):
    """
    将全天按固定窗口分段，避免单次查询被平台返回条数上限截断

    Args:
        day_start: 查询起始时间
        day_end: 查询结束时间
        segment_minutes: 每个分段的时长（分钟）

    Returns:
        list: 时间段列表，每个元素为 (start_str, end_str) 元组
              时间格式为 YYYYMMDDHHMMSS
    """
    if segment_minutes <= 0:
        segment_minutes = 180
    step = timedelta(minutes=segment_minutes)
    cursor = day_start
    ranges = []
    while cursor <= day_end:
        # 计算当前分段的结束时间
        seg_end = min(cursor + step - timedelta(seconds=1), day_end)
        ranges.append((_format_music_time(cursor), _format_music_time(seg_end)))
        # 移动游标到下一个分段的开始
        cursor = seg_end + timedelta(seconds=1)
    return ranges


def _query_file_list_by_range(client, user_id, pwd, interface_id, base_params, start_time: str, end_time: str):
    """
    按时间段查询天气预警数据。

    约定：
    - start_time/end_time 传入格式为 YYYYMMDDHHMMSS；
    - timeRange 使用格林威治时间；
    - getSevpEleByTimeRange 返回 JSON 字符串，因此使用 callAPI_to_serializedStr。
    """
    params = dict(base_params)
    params["timeRange"] = f"[{start_time},{end_time}]"

    # 有些平台接口参数写作 timerange，这里两个都传，增强兼容性。
    params["timerange"] = f"[{start_time},{end_time}]"

    ret_text = client.callAPI_to_serializedStr(
        user_id,
        pwd,
        interface_id,
        params,
        "json",
    )

    if not ret_text:
        return []

    if isinstance(ret_text, bytes):
        ret_text = ret_text.decode("utf-8", errors="replace")

    ret_text = str(ret_text).strip()

    if ret_text.startswith("Error") or ret_text.startswith("getway error"):
        raise RuntimeError(f"MUSIC 接口返回失败: {ret_text}")

    try:
        data = json.loads(ret_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MUSIC 接口返回内容不是合法 JSON: {ret_text[:500]}") from exc

    return_code = str(data.get("returnCode", ""))
    if return_code not in ("0", ""):
        raise RuntimeError(
            f"MUSIC 接口返回失败: returnCode={data.get('returnCode')}, "
            f"returnMessage={data.get('returnMessage')}"
        )

    ds = data.get("DS", [])
    if not isinstance(ds, list):
        return []

    return ds


def query_warning_records(time_param=None):
    """
    查询天气预警 JSON 数据。

    - 不传 time_param：按格林威治时间查询当前时刻往前 2 小时；
    - 传入 time_param：按传入时间所在当天查询，并转换为格林威治时间；
    - 返回接口 DS 数组。
    """
    client = _get_client()
    user_id = MUSIC_USER_ID
    pwd = MUSIC_PASSWORD
    interface_id = MUSIC_INTERFACE_ID

    base_params = dict(MUSIC_RADAR_DEFAULT_PARAMS)
    base_params.pop("time", None)
    base_params.pop("startTime", None)
    base_params.pop("endTime", None)

    if not time_param:
        end_dt = datetime.utcnow().replace(microsecond=0)
        start_dt = end_dt - timedelta(hours=MUSIC_DEFAULT_LOOKBACK_HOURS)
    else:
        day_start, day_end = _calculate_day_bounds(time_param)
        if MUSIC_FILE_TIME_IS_UTC:
            start_dt = day_start - timedelta(hours=LOCAL_TIME_OFFSET_HOURS)
            end_dt = day_end - timedelta(hours=LOCAL_TIME_OFFSET_HOURS)
        else:
            start_dt = day_start
            end_dt = day_end

    start_time = _format_music_time(start_dt)
    end_time = _format_music_time(end_dt)

    return _query_file_list_by_range(
        client,
        user_id,
        pwd,
        interface_id,
        base_params,
        start_time,
        end_time,
    )
