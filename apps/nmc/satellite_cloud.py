import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SATELLITE_CLOUD_PAGE_URL = (
    "https://weather.cma.cn/web/channel-2b0863600e144b13807e606f928b1266.html"
)
SATELLITE_CLOUD_DIR_NAME = "satellite_cloud"
SATELLITE_CLOUD_PREFIX = "satellite_cloud_"
REQUEST_TIMEOUT = 20


@dataclass
class SatelliteCloudItem:
    source_url: str
    display_time: str
    image_time: datetime


class _TimeListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_time_list = False
        self._current_value = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag == "select" and attr_map.get("id") == "timeList":
            self._in_time_list = True
            return

        if self._in_time_list and tag == "option":
            self._current_value = attr_map.get("value")

    def handle_endtag(self, tag):
        if tag == "select" and self._in_time_list:
            self._in_time_list = False
        if self._in_time_list and tag == "option":
            self._current_value = None

    def handle_data(self, data):
        if self._in_time_list and self._current_value:
            text = data.strip()
            if text:
                self.items.append((self._current_value, text))


def satellite_cloud_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / SATELLITE_CLOUD_DIR_NAME


def _build_media_url(filename: str) -> str:
    media_url = str(settings.MEDIA_URL)
    if not media_url.endswith("/"):
        media_url = f"{media_url}/"
    return f"{media_url}{SATELLITE_CLOUD_DIR_NAME}/{filename}"


def _parse_display_time(text: str) -> datetime:
    match = re.search(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时(\d{1,2})分",
        text,
    )
    if not match:
        raise ValueError(f"卫星云图时间格式无法解析: {text}")
    year, month, day, hour, minute = (int(part) for part in match.groups())
    return datetime(year, month, day, hour, minute, 0)


def _filename_for_item(item: SatelliteCloudItem) -> str:
    suffix = Path(urlparse(item.source_url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        suffix = ".jpg"
    return f"{SATELLITE_CLOUD_PREFIX}{item.image_time.strftime('%Y%m%d%H%M%S')}{suffix}"


def _meta_path_for_image(image_path: Path) -> Path:
    return image_path.with_suffix(".json")


def fetch_satellite_cloud_items() -> List[SatelliteCloudItem]:
    response = requests.get(
        SATELLITE_CLOUD_PAGE_URL,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ReflectanceApiService/1.0)",
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"

    parser = _TimeListParser()
    parser.feed(response.text)

    items: List[SatelliteCloudItem] = []
    seen = set()
    for source_url, display_time in parser.items:
        try:
            image_time = _parse_display_time(display_time)
        except ValueError:
            logger.warning("跳过无法解析时间的卫星云图: %s", display_time)
            continue

        absolute_url = urljoin(SATELLITE_CLOUD_PAGE_URL, source_url)
        cache_key = image_time.strftime("%Y%m%d%H%M%S")
        if cache_key in seen:
            continue
        seen.add(cache_key)

        items.append(
            SatelliteCloudItem(
                source_url=absolute_url,
                display_time=display_time,
                image_time=image_time,
            )
        )

    items.sort(key=lambda item: item.image_time, reverse=True)
    return items


def _write_metadata(meta_path: Path, item: SatelliteCloudItem, filename: str) -> None:
    meta = {
        "time": item.image_time.strftime("%Y-%m-%d %H:%M:%S"),
        "display_time": item.display_time,
        "source_url": item.source_url,
        "filename": filename,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _download_image(item: SatelliteCloudItem, image_path: Path) -> None:
    response = requests.get(
        item.source_url,
        timeout=REQUEST_TIMEOUT,
        stream=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ReflectanceApiService/1.0)",
            "Referer": SATELLITE_CLOUD_PAGE_URL,
        },
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and "image" not in content_type:
        raise ValueError(f"下载内容不是图片: {content_type}")

    tmp_path = image_path.with_suffix(f"{image_path.suffix}.tmp")
    with tmp_path.open("wb") as fp:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if chunk:
                fp.write(chunk)
    os.replace(tmp_path, image_path)


def sync_satellite_cloud_images(limit: Optional[int] = None) -> Dict[str, Any]:
    """
    抓取 CMA FY4B 卫星云图列表，按北京时间时次落盘。
    已存在的本地图片会跳过，不重复下载。
    """
    items = fetch_satellite_cloud_items()
    if limit is not None and limit > 0:
        items = items[:limit]

    img_dir = satellite_cloud_dir()
    img_dir.mkdir(parents=True, exist_ok=True)

    created = []
    skipped = []
    failed = []

    for item in items:
        filename = _filename_for_item(item)
        image_path = img_dir / filename
        meta_path = _meta_path_for_image(image_path)

        if image_path.exists():
            if not meta_path.exists():
                try:
                    _write_metadata(meta_path, item, filename)
                except OSError:
                    logger.exception("卫星云图元数据写入失败: %s", meta_path)
            skipped.append(filename)
            continue

        try:
            _download_image(item, image_path)
            _write_metadata(meta_path, item, filename)
            created.append(filename)
        except Exception as exc:
            failed.append({"filename": filename, "error": str(exc)})
            logger.exception("卫星云图下载失败: %s", item.source_url)

    return {
        "total": len(items),
        "created": len(created),
        "skipped": len(skipped),
        "failed": len(failed),
        "created_files": created,
        "failed_files": failed,
    }


def _load_meta(image_path: Path) -> Dict[str, Any]:
    meta_path = _meta_path_for_image(image_path)
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("卫星云图元数据读取失败: %s", meta_path)
    return {}


def _image_time_from_path(image_path: Path, meta: Dict[str, Any]) -> Optional[datetime]:
    time_text = meta.get("time")
    if time_text:
        try:
            return datetime.strptime(str(time_text), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    stem = image_path.stem.replace(SATELLITE_CLOUD_PREFIX, "", 1)
    try:
        return datetime.strptime(stem, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def list_local_satellite_cloud_images(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    img_dir = satellite_cloud_dir()
    if not img_dir.is_dir():
        return []

    results = []
    for image_path in img_dir.glob(f"{SATELLITE_CLOUD_PREFIX}*"):
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue

        meta = _load_meta(image_path)
        image_time = _image_time_from_path(image_path, meta)
        results.append(
            {
                "filename": image_path.name,
                "url": _build_media_url(image_path.name),
                "path": str(image_path),
                "time": (
                    image_time.strftime("%Y-%m-%d %H:%M:%S")
                    if image_time
                    else meta.get("time")
                ),
                "display_time": meta.get("display_time"),
                "source_url": meta.get("source_url"),
            }
        )

    results.sort(key=lambda item: item.get("time") or "", reverse=True)
    if limit is not None and limit > 0:
        return results[:limit]
    return results
