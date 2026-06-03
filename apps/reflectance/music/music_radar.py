import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import re
import tempfile

from reflectance.music.radar_rest import (
    DATA_FORMAT,
    PASSWORD as REST_PASSWORD,
    RADAR_DATA_CODE,
    RADAR_INTERFACE_ID,
    USER_ID as REST_USER_ID,
    query_radar_files_by_time_range,
)

# 配置 MUSIC SDK 的源码路径，将其添加到 Python 模块搜索路径中

# ==================== MUSIC 平台配置 ====================
# MUSIC 客户端配置文件路径
MUSIC_USER_ID = REST_USER_ID
# MUSIC 平台认证密码
MUSIC_PASSWORD = REST_PASSWORD
# MUSIC 接口ID：根据时间范围查询雷达文件
MUSIC_INTERFACE_ID = RADAR_INTERFACE_ID
# MUSIC 雷达数据查询默认参数
MUSIC_RADAR_DEFAULT_PARAMS = {
    "dataCode": RADAR_DATA_CODE,
    "dataFormat": DATA_FORMAT,
}
_APPS_DIR = Path(__file__).resolve().parents[2]
RADAR_BIN_CACHE_DIR = _APPS_DIR / "img" / "radar_bin"
# MUSIC 查询分段时长（分钟）：每次查询3小时，规避单次条数上限截断
MUSIC_QUERY_SEGMENT_MINUTES = 180
# MUSIC 文件时次是否为 UTC（格林威治时间）
MUSIC_FILE_TIME_IS_UTC = True
# 本地业务时区相对 UTC 的偏移小时（北京时间 +8）
LOCAL_TIME_OFFSET_HOURS = 8


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


def _query_file_list_by_range(base_params, start_time: str, end_time: str):
    """
    按时间段查询单次文件列表。
    约定：start_time/end_time 传入为本地业务时间（北京时间），
    发送到 MUSIC 前按平台时区语义转换（当前平台为 UTC，需 -8h）。
    """
    start_dt = datetime.strptime(start_time, "%Y%m%d%H%M%S")
    end_dt = datetime.strptime(end_time, "%Y%m%d%H%M%S")
    if MUSIC_FILE_TIME_IS_UTC:
        start_dt = start_dt - timedelta(hours=LOCAL_TIME_OFFSET_HOURS)
        end_dt = end_dt - timedelta(hours=LOCAL_TIME_OFFSET_HOURS)

    time_range = f"[{_format_music_time(start_dt)},{_format_music_time(end_dt)}]"
    return query_radar_files_by_time_range(time_range)


def _dedup_extend(dst, seen, file_infos):
    """将 file_infos 追加到 dst，并按 (fileName,fileUrl) 去重。"""
    for fi in file_infos:
        key = (
            str(getattr(fi, "fileName", "") or ""),
            str(getattr(fi, "fileUrl", "") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        dst.append(fi)


def _has_candidate_not_later_than(file_infos, req_dt: datetime) -> bool:
    """判断分段结果中是否存在 <= 请求时刻的候选文件。"""
    for fi in file_infos:
        ft = _extract_file_time(fi)
        if ft is None:
            continue
        if ft.replace(tzinfo=None, microsecond=0) <= req_dt:
            return True
    return False


def _find_segment_index(segment_ranges, req_dt: datetime) -> int:
    """定位请求时刻落在哪个分段。"""
    for idx, (start_s, end_s) in enumerate(segment_ranges):
        seg_start = datetime.strptime(start_s, "%Y%m%d%H%M%S")
        seg_end = datetime.strptime(end_s, "%Y%m%d%H%M%S")
        if seg_start <= req_dt <= seg_end:
            return idx
    return len(segment_ranges) - 1


def _query_radar_files(time_param=None):
    """
    从 MUSIC 平台查询雷达文件列表

    采用分段查询策略，将全天分为多个3小时窗口进行查询，
    避免因平台单次返回条数限制导致数据截断

    Args:
        time_param: 可选的时间参数，用于确定查询哪一天的数据

    Returns:
        list: 雷达文件信息列表（已去重）

    Raises:
        RuntimeError: 当 MUSIC 接口调用失败或未返回任何文件时抛出
    """
    # 复制默认参数，移除不需要的字段
    base_params = dict(MUSIC_RADAR_DEFAULT_PARAMS)
    base_params.pop("time", None)
    base_params.pop("startTime", None)
    base_params.pop("endTime", None)
    base_params.pop("timeRange", None)

    # getRadaFileByTimeRange 使用 timerange，不接受 startTime/endTime
    day_start, day_end = _calculate_day_bounds(time_param)
    segment_ranges = _iter_segment_ranges(day_start, day_end, MUSIC_QUERY_SEGMENT_MINUTES)

    merged_file_infos = []
    seen = set()  # 用于去重的集合

    if not time_param:
        # 未指定时次：从当天最后分段向前查询，命中首个非空分段即停止。
        for start_time, end_time in reversed(segment_ranges):
            part = _query_file_list_by_range(base_params, start_time, end_time)
            if not part:
                continue
            _dedup_extend(merged_file_infos, seen, part)
            break
    else:
        req_dt = _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)
        req_idx = _find_segment_index(segment_ranges, req_dt)

        # 1) 先查请求时刻所在分段，并向前扩窗；命中 <= 请求时刻数据就早停。
        found_not_later = False
        for i in range(req_idx, -1, -1):
            start_time, end_time = segment_ranges[i]
            part = _query_file_list_by_range(base_params, start_time, end_time)
            _dedup_extend(merged_file_infos, seen, part)
            if _has_candidate_not_later_than(part, req_dt):
                found_not_later = True
                break

        # 2) 若请求时刻早于当天最早文件（前向全未命中且当前为空），向后查到首个非空分段即可。
        if not found_not_later and not merged_file_infos:
            for i in range(req_idx + 1, len(segment_ranges)):
                start_time, end_time = segment_ranges[i]
                part = _query_file_list_by_range(base_params, start_time, end_time)
                if not part:
                    continue
                _dedup_extend(merged_file_infos, seen, part)
                break

    if not merged_file_infos:
        raise RuntimeError("MUSIC 未返回任何雷达文件")

    return merged_file_infos


def _extract_file_time(file_info):
    """
    从 file_info 的常见时间字段或文件名中提取时间

    支持格式：
    - YYYYMMDD_HHMMSS (如 20260515_120100)
    - YYYYMMDDHHMMSS (如 20260515120100)

    Args:
        file_info: MUSIC 平台返回的文件信息对象

    Returns:
        datetime or None: 提取到的时间对象，如果无法提取则返回 None
    """
    # 先尝试从对象字段中提取时间（若接口有返回）
    for key in ("time", "fileTime", "obsTime", "validTime", "startTime", "endTime"):
        v = getattr(file_info, key, None)
        if v:
            s = str(v).strip()
            for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return _normalize_file_time(datetime.strptime(s, fmt))
                except ValueError:
                    continue

    # 兜底方案：从文件名中提取时间
    name = str(getattr(file_info, "fileName", "") or "")
    if not name:
        return None

    # 文件名常见有多个时间戳，优先取最后一个（更接近产品时次）
    # 匹配格式：YYYYMMDD_HHMMSS
    m1 = re.findall(r"(\d{8}_\d{6})", name)
    if m1:
        try:
            return _normalize_file_time(datetime.strptime(m1[-1], "%Y%m%d_%H%M%S"))
        except ValueError:
            pass

    # 匹配格式：YYYYMMDDHHMMSS
    m2 = re.findall(r"(\d{14})", name)
    if m2:
        try:
            return _normalize_file_time(datetime.strptime(m2[-1], "%Y%m%d%H%M%S"))
        except ValueError:
            pass

    return None


def _pick_target_file(file_infos, time_param=None):
    """
    从文件列表中选取要渲染的目标 bin 文件

    选择策略：
    - 未传 time：取时间最新的一条
    - 传了 time：
        1. 优先精确匹配请求时间
        2. 否则取 <= time 的最近一条（向上回溯）
        3. 若当天都比 time 晚，则退化取最早一条

    Args:
        file_infos: 文件信息列表
        time_param: 可选的时间参数

    Returns:
        object: 选中的文件信息对象

    Raises:
        RuntimeError: 当文件列表为空时抛出
    """
    if not file_infos:
        raise RuntimeError("MUSIC 未返回任何雷达文件")

    # 未指定时间参数时，取最新的文件
    if not time_param:
        candidates = []
        for fi in file_infos:
            ft = _extract_file_time(fi)
            if ft is not None:
                candidates.append((ft.replace(tzinfo=None, microsecond=0), fi))
        if candidates:
            return max(candidates, key=lambda x: x[0])[1]
        return file_infos[0]

    # 解析请求时间
    req = _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)
    candidates = []
    for fi in file_infos:
        ft = _extract_file_time(fi)
        if ft is not None:
            candidates.append((ft.replace(tzinfo=None, microsecond=0), fi))

    # 无法解析时次时，回退旧行为
    if not candidates:
        return file_infos[0]

    # 精确命中：查找与请求时间完全匹配的文件
    for ft, fi in candidates:
        if ft == req:
            return fi

    # 向上查询：取不晚于请求时刻的最近一条
    earlier_or_equal = [(ft, fi) for ft, fi in candidates if ft <= req]
    if earlier_or_equal:
        return max(earlier_or_equal, key=lambda x: x[0])[1]

    # 全部都晚于请求时刻时，兜底取最早一条
    return min(candidates, key=lambda x: x[0])[1]


def _format_selected_time(file_info) -> str:
    """
    格式化选中文件的时间为可读字符串

    Args:
        file_info: 文件信息对象

    Returns:
        str: 格式化后的时间字符串 (YYYY-MM-DD HH:MM:SS)，如果无法提取则返回空字符串
    """
    dt = _extract_file_time(file_info)
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def radar_bin_path(request=None):
    """
    上下文管理器：从 MUSIC 获取雷达 .bin 文件

    功能说明：
    - 根据请求参数查询雷达文件
    - 下载 bin 到项目目录 apps/img/radar_bin/（已存在则复用，不自动删除）

    时间规则：从每小时0分开始，每6分钟刷新一次（00,06,12,18,24,30,36,42,48,54）

    用法示例:
        with radar_bin_path(request) as (file_path, selected_time):
            f = cinrad.io.MocMosaic(str(file_path))

    Args:
        request: DRF 请求对象，从 request.data 读取 time（可选）

    Yields:
        tuple: (cache_file, selected_time)
            - cache_file: 缓存的 bin 文件路径 (Path 对象)
            - selected_time: 选中文件的时间字符串 (YYYY-MM-DD HH:MM:SS)
    """
    # 从 GET Query 读取 time
    time_param = request.query_params.get("time") if request else None

    # 查询雷达文件列表
    file_infos = _query_radar_files(time_param)
    # 选取目标文件
    latest = _pick_target_file(file_infos, time_param)
    # 格式化选中文件的时间
    selected_time = _format_selected_time(latest)
    suffix = Path(latest.fileName).suffix.lower()

    if suffix in {".png", ".jpg", ".jpeg"}:
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            _download_bin_file(latest.fileUrl, tmp_path)
            yield tmp_path, selected_time
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
        return

    # bin 落盘到项目内目录，避免同一文件反复下载
    cache_dir = RADAR_BIN_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    # 构造缓存文件路径
    cache_file = cache_dir / Path(latest.fileName).name

    # 如果缓存文件不存在，则下载
    if not cache_file.exists():
        _download_bin_file(latest.fileUrl, cache_file)

    yield cache_file, selected_time


def _download_bin_file(file_url, dest_path):
    """
    从指定 URL 下载 bin 文件到本地路径

    Args:
        file_url: 文件下载地址
        dest_path: 本地保存路径 (Path 对象或字符串)

    Returns:
        Path: 下载完成的文件路径
    """
    req = urllib.request.Request(file_url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    suffix = Path(dest_path).suffix.lower()
    if suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        preview = data[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"下载到的雷达图片无效: {preview}")
    if suffix in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
        preview = data[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"下载到的雷达图片无效: {preview}")
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path


def _download_bin_file(file_url, dest_path):
    req = urllib.request.Request(file_url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path
