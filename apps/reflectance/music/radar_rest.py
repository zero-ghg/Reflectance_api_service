import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import requests
from reflectance.demo.util import SignGenUtil

SERVICE_NODE_ID = "NMIC_MUSIC_CMADAAS"
SERVICE_IP = "60.29.105.45:19080"
USER_ID = "BETJ_FLZX_FLPT"
PASSWORD = "Fanglei@2026"
RADAR_INTERFACE_ID = "getRadaFileByTimeRange"
RADAR_DATA_CODE = "RADA_CHN_CWR_L3_RNET"
DATA_FORMAT = "json"
REQUEST_TIMEOUT = 60


def _get_row_value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def _file_info_from_row(row):
    file_name = _get_row_value(row, "FILE_NAME", "fileName", "file_name", "NAME", "name")
    file_url = _get_row_value(row, "FILE_URL", "TDS_URL", "fileUrl", "file_url", "tdsUrl", "tds_url")
    suffix = _get_row_value(row, "FORMAT", "format", "SUFFIX", "suffix")
    size = _get_row_value(row, "FILE_SIZE", "fileSize", "file_size", "SIZE", "size")
    return SimpleNamespace(
        fileName=str(file_name or Path(str(file_url)).name),
        savePath="",
        suffix=str(suffix or ""),
        size=str(size or ""),
        fileUrl=str(file_url or ""),
        imgBase64="",
        attributes=row,
    )


def _parse_file_infos(data):
    rows = data.get("DS") or data.get("ds") or data.get("data") or data.get("files") or []
    if isinstance(rows, dict):
        rows = rows.get("DS") or rows.get("data") or rows.get("files") or []
    if not isinstance(rows, list):
        return []
    return [_file_info_from_row(row) for row in rows if isinstance(row, dict)]


def build_file_list_url(interface_id, data_code, time_range, extra_params=None):
    timestamp = str(int(round(time.time() * 1000)))
    nonce = str(uuid.uuid1())
    query = {
        "serviceNodeId": SERVICE_NODE_ID,
        "userId": USER_ID,
        "pwd": PASSWORD,
        "interfaceId": interface_id,
        "dataCode": data_code,
        "timeRange": time_range,
        "dataFormat": DATA_FORMAT,
        "timestamp": timestamp,
        "nonce": nonce,
    }
    if extra_params:
        query.update({k: v for k, v in extra_params.items() if v not in (None, "")})
    sign = SignGenUtil.SignGenUtil().getSign(dict(query))
    if not sign or sign == "generate sign error":
        raise RuntimeError(f"generate sign failed: {sign}")
    query["sign"] = sign
    return f"http://{SERVICE_IP}/music-ws/api?{urlencode(query)}"


def query_music_files_by_time_range(interface_id, data_code, time_range, extra_params=None):
    url = build_file_list_url(interface_id, data_code, time_range, extra_params)
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"radar REST interface returned invalid JSON: {response.text[:500]}") from exc

    return_code = data.get("returnCode", data.get("code", 0))
    try:
        return_code = int(return_code)
    except (TypeError, ValueError):
        return_code = 0
    if return_code != 0:
        message = data.get("returnMessage") or data.get("message") or data.get("msg") or ""
        raise RuntimeError(f"radar REST interface failed: returnCode={return_code}, message={message}")

    return _parse_file_infos(data)


def build_radar_file_list_url(time_range):
    return build_file_list_url(RADAR_INTERFACE_ID, RADAR_DATA_CODE, time_range)


def query_radar_files_by_time_range(time_range):
    return query_music_files_by_time_range(RADAR_INTERFACE_ID, RADAR_DATA_CODE, time_range)
