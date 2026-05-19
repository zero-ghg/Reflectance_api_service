import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

from reflectance.music.music_radar import (
    LOCAL_TIME_OFFSET_HOURS,
    MUSIC_PASSWORD,
    MUSIC_FILE_TIME_IS_UTC,
    MUSIC_USER_ID,
    RADAR_BIN_CACHE_DIR,
    _calculate_day_bounds,
    _dedup_extend,
    _download_bin_file,
    _extract_file_time,
    _find_segment_index,
    _format_music_time,
    _get_client,
    _has_candidate_not_later_than,
    _iter_segment_ranges,
    _normalize_file_time,
    _parse_front_time,
)

MUSIC_PRECIPITATION_INTERFACE_ID = "getRadaMosaicProductByTimeRange"
PRECIPITATION_BIN_CACHE_DIR = RADAR_BIN_CACHE_DIR.parent / "precipitation_bin"


@dataclass(frozen=True)
class PrecipitationProduct:
    key: str
    label: str
    data_code: str
    bin_dir_name: str
    query_segment_minutes: int
    include_tds_path: bool = False


PRECIPITATION_PRODUCTS: Dict[str, PrecipitationProduct] = {
    "1h": PrecipitationProduct(
        key="1h",
        label="1小时降水概率",
        data_code="RADA_L3_MST_PRE_HOR6_QC",
        bin_dir_name="one_hour",
        query_segment_minutes=180,
    ),
    "3h": PrecipitationProduct(
        key="3h",
        label="3小时降水概率",
        data_code="RADA_L3_MST_QPE03_QC",
        bin_dir_name="three_hour",
        query_segment_minutes=360,
        include_tds_path=True,
    ),
}

_PRODUCT_ALIASES = {
    "1": "1h",
    "1h": "1h",
    "one-hour": "1h",
    "one_hour": "1h",
    "hour1": "1h",
    "3": "3h",
    "3h": "3h",
    "three-hour": "3h",
    "three_hour": "3h",
    "hour3": "3h",
}


def get_precipitation_product(product_key: str) -> PrecipitationProduct:
    normalized = _PRODUCT_ALIASES.get(str(product_key).strip().lower())
    if not normalized or normalized not in PRECIPITATION_PRODUCTS:
        raise ValueError(f"不支持的降水产品类型: {product_key}")
    return PRECIPITATION_PRODUCTS[normalized]


def _precipitation_base_params(product: PrecipitationProduct):
    params = {
        "dataCode": product.data_code,
        "dataFormat": "json",
        "limitCnt": "50",
    }
    if product.include_tds_path:
        params["tdspath"] = "true"
    return params


def _query_precipitation_file_list_by_range(
    client,
    product: PrecipitationProduct,
    base_params,
    start_time: str,
    end_time: str,
):
    start_dt = datetime.strptime(start_time, "%Y%m%d%H%M%S")
    end_dt = datetime.strptime(end_time, "%Y%m%d%H%M%S")
    if MUSIC_FILE_TIME_IS_UTC:
        start_dt = start_dt.replace(tzinfo=None) - _local_offset()
        end_dt = end_dt.replace(tzinfo=None) - _local_offset()

    params = dict(base_params)
    params["timeRange"] = f"[{_format_music_time(start_dt)},{_format_music_time(end_dt)}]"
    ret = client.callAPI_to_fileList(
        MUSIC_USER_ID,
        MUSIC_PASSWORD,
        MUSIC_PRECIPITATION_INTERFACE_ID,
        params,
    )
    if ret.request.errorCode != 0:
        raise RuntimeError(f"MUSIC {product.label}接口返回失败: {ret.request.errorMessage}")
    return ret.fileInfos or []


def _local_offset():
    return timedelta(hours=LOCAL_TIME_OFFSET_HOURS)


def _query_precipitation_files(product: PrecipitationProduct, time_param=None):
    client = _get_client()
    day_start, day_end = _calculate_day_bounds(time_param)
    segment_ranges = _iter_segment_ranges(day_start, day_end, product.query_segment_minutes)

    merged_file_infos = []
    seen = set()
    base_params = _precipitation_base_params(product)

    if not time_param:
        for start_time, end_time in reversed(segment_ranges):
            part = _query_precipitation_file_list_by_range(
                client,
                product,
                base_params,
                start_time,
                end_time,
            )
            if not part:
                continue
            _dedup_extend(merged_file_infos, seen, part)
            break
    else:
        req_dt = _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)
        req_idx = _find_segment_index(segment_ranges, req_dt)

        found_not_later = False
        for i in range(req_idx, -1, -1):
            start_time, end_time = segment_ranges[i]
            part = _query_precipitation_file_list_by_range(
                client,
                product,
                base_params,
                start_time,
                end_time,
            )
            _dedup_extend(merged_file_infos, seen, part)
            if _has_candidate_not_later_than(part, req_dt):
                found_not_later = True
                break

        if not found_not_later and not merged_file_infos:
            for i in range(req_idx + 1, len(segment_ranges)):
                start_time, end_time = segment_ranges[i]
                part = _query_precipitation_file_list_by_range(
                    client,
                    product,
                    base_params,
                    start_time,
                    end_time,
                )
                if not part:
                    continue
                _dedup_extend(merged_file_infos, seen, part)
                break

    if not merged_file_infos:
        raise RuntimeError(f"MUSIC 未返回任何{product.label}文件")

    return merged_file_infos


def _extract_publish_time(file_info):
    name = str(getattr(file_info, "fileName", "") or "")
    matches = re.findall(r"(\d{14})", name)
    if not matches:
        return None
    try:
        return _normalize_file_time(datetime.strptime(matches[0], "%Y%m%d%H%M%S"))
    except ValueError:
        return None


def _pick_precipitation_file(file_infos, time_param=None):
    if not file_infos:
        raise RuntimeError("MUSIC 未返回任何降水文件")

    candidates = []
    for fi in file_infos:
        valid_time = _extract_file_time(fi)
        if valid_time is None:
            continue
        publish_time = _extract_publish_time(fi)
        candidates.append(
            (
                valid_time.replace(tzinfo=None, microsecond=0),
                publish_time.replace(tzinfo=None, microsecond=0) if publish_time else datetime.min,
                fi,
            )
        )

    if not candidates:
        return file_infos[0]

    if not time_param:
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    req = _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)

    exact = [item for item in candidates if item[0] == req]
    if exact:
        return max(exact, key=lambda item: item[1])[2]

    earlier_or_equal = [item for item in candidates if item[0] <= req]
    if earlier_or_equal:
        return max(earlier_or_equal, key=lambda item: (item[0], item[1]))[2]

    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _format_selected_time(file_info) -> str:
    dt = _extract_file_time(file_info)
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def precipitation_bin_path(product_key: str, request=None):
    product = get_precipitation_product(product_key)
    time_param = request.query_params.get("time") if request else None
    file_infos = _query_precipitation_files(product, time_param)
    latest = _pick_precipitation_file(file_infos, time_param)
    selected_time = _format_selected_time(latest)

    cache_dir = PRECIPITATION_BIN_CACHE_DIR / product.bin_dir_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / Path(latest.fileName).name

    if not cache_file.exists():
        if not getattr(latest, "fileUrl", ""):
            raise RuntimeError(f"{product.label}文件缺少下载地址")
        _download_bin_file(latest.fileUrl, cache_file)

    yield cache_file, selected_time
