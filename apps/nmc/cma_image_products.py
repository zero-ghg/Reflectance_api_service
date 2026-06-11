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

REQUEST_TIMEOUT = 20
CMA_IMAGE_PRODUCT_DIR_NAME = "cma_image_products"
CMA_IMAGE_PREFIX = "cma_"


@dataclass(frozen=True)
class CmaImageProductConfig:
    key: str
    label: str
    page_url: str
    description: str


@dataclass
class CmaImageProductItem:
    product: CmaImageProductConfig
    source_url: str
    image_time: datetime
    title: Optional[str] = None


CMA_IMAGE_PRODUCTS = {
    "precipitation": CmaImageProductConfig(
        key="precipitation",
        label="降水量",
        page_url="https://weather.cma.cn/web/channel-18.html",
        description="近10天降水距平百分率",
    ),
    "temperature": CmaImageProductConfig(
        key="temperature",
        label="气温",
        page_url="https://weather.cma.cn/web/channel-32.html",
        description="近10天全国平均气温距平图",
    ),
}


class _CmaProductPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image_url = None
        self.title = None
        self._in_title = False
        self._title_chunks = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if tag == "img" and attr_map.get("id") == "imgPath":
            self.image_url = attr_map.get("src")
        if tag == "div":
            classes = attr_map.get("class", "").split()
            if "ptitle" in classes:
                self._in_title = True
                self._title_chunks = []

    def handle_endtag(self, tag):
        if tag == "div" and self._in_title:
            title = "".join(self._title_chunks).strip()
            self.title = title or self.title
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self._title_chunks.append(data)


def get_cma_image_product(product_key: str) -> CmaImageProductConfig:
    try:
        return CMA_IMAGE_PRODUCTS[product_key]
    except KeyError as exc:
        raise ValueError(f"不支持的产品: {product_key}") from exc


def cma_image_product_dir(product_key: str) -> Path:
    return Path(settings.MEDIA_ROOT) / CMA_IMAGE_PRODUCT_DIR_NAME / product_key


def _build_media_url(product_key: str, filename: str) -> str:
    media_url = str(settings.MEDIA_URL)
    if not media_url.endswith("/"):
        media_url = f"{media_url}/"
    return f"{media_url}{CMA_IMAGE_PRODUCT_DIR_NAME}/{product_key}/{filename}"


def _parse_time_from_source_url(source_url: str) -> datetime:
    path = urlparse(source_url).path
    filename = Path(path).name
    match = re.search(r"_(\d{14})(?:\d{3})?\.[^.]+$", filename)
    if not match:
        match = re.search(r"(\d{14})", filename)
    if not match:
        raise ValueError(f"无法从图片文件名解析时次: {filename}")
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")


def _filename_for_item(item: CmaImageProductItem) -> str:
    suffix = Path(urlparse(item.source_url).path).suffix.lower()
    if suffix not in {".gif", ".jpg", ".jpeg", ".png"}:
        suffix = ".png"
    time_key = item.image_time.strftime("%Y%m%d%H%M%S")
    return f"{CMA_IMAGE_PREFIX}{item.product.key}_{time_key}{suffix}"


def _meta_path_for_image(image_path: Path) -> Path:
    return image_path.with_suffix(".json")


def fetch_cma_image_product_item(product_key: str) -> CmaImageProductItem:
    product = get_cma_image_product(product_key)
    response = requests.get(
        product.page_url,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ReflectanceApiService/1.0)",
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"

    parser = _CmaProductPageParser()
    parser.feed(response.text)

    if not parser.image_url:
        raise ValueError(f"{product.label}页面未找到 imgPath 图片地址")

    source_url = urljoin(product.page_url, parser.image_url)
    image_time = _parse_time_from_source_url(source_url)

    return CmaImageProductItem(
        product=product,
        source_url=source_url,
        image_time=image_time,
        title=parser.title,
    )


def _write_metadata(meta_path: Path, item: CmaImageProductItem, filename: str) -> None:
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "product": item.product.key,
        "product_name": item.product.label,
        "description": item.title or item.product.description,
        "time": item.image_time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_url": item.source_url,
        "page_url": item.product.page_url,
        "filename": filename,
        "fetched_at": now_text,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _download_image(item: CmaImageProductItem, image_path: Path) -> None:
    response = requests.get(
        item.source_url,
        timeout=REQUEST_TIMEOUT,
        stream=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ReflectanceApiService/1.0)",
            "Referer": item.product.page_url,
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


def sync_cma_image_product(product_key: str) -> Dict[str, Any]:
    item = fetch_cma_image_product_item(product_key)
    img_dir = cma_image_product_dir(product_key)
    img_dir.mkdir(parents=True, exist_ok=True)

    filename = _filename_for_item(item)
    image_path = img_dir / filename
    meta_path = _meta_path_for_image(image_path)
    created = False

    if image_path.exists():
        if not meta_path.exists():
            _write_metadata(meta_path, item, filename)
    else:
        _download_image(item, image_path)
        _write_metadata(meta_path, item, filename)
        created = True

    return {
        "product": product_key,
        "time": item.image_time.strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename,
        "created": created,
        "skipped": not created,
    }


def sync_cma_image_products(product_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    keys = product_keys or list(CMA_IMAGE_PRODUCTS.keys())
    results = []
    failed = []

    for product_key in keys:
        try:
            results.append(sync_cma_image_product(product_key))
        except Exception as exc:
            failed.append({"product": product_key, "error": str(exc)})
            logger.exception("CMA 图片产品同步失败: %s", product_key)

    return {
        "total": len(keys),
        "created": sum(1 for item in results if item.get("created")),
        "skipped": sum(1 for item in results if item.get("skipped")),
        "failed": len(failed),
        "results": results,
        "failed_items": failed,
    }


def _load_meta(image_path: Path) -> Dict[str, Any]:
    meta_path = _meta_path_for_image(image_path)
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("CMA 图片产品元数据读取失败: %s", meta_path)
    return {}


def _image_time_from_path(image_path: Path, meta: Dict[str, Any]) -> Optional[datetime]:
    time_text = meta.get("time")
    if time_text:
        try:
            return datetime.strptime(str(time_text), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    match = re.search(r"_(\d{14})$", image_path.stem)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    return None


def _local_image_result(product_key: str, image_path: Path) -> Dict[str, Any]:
    meta = _load_meta(image_path)
    image_time = _image_time_from_path(image_path, meta)
    return {
        "product": product_key,
        "product_name": meta.get("product_name"),
        "description": meta.get("description"),
        "filename": image_path.name,
        "url": _build_media_url(product_key, image_path.name),
        "path": str(image_path),
        "time": (
            image_time.strftime("%Y-%m-%d %H:%M:%S")
            if image_time
            else meta.get("time")
        ),
        "source_url": meta.get("source_url"),
        "page_url": meta.get("page_url"),
        "fetched_at": meta.get("fetched_at"),
    }


def list_local_cma_image_products(product_key: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    get_cma_image_product(product_key)
    img_dir = cma_image_product_dir(product_key)
    if not img_dir.is_dir():
        return []

    results = []
    for image_path in img_dir.glob(f"{CMA_IMAGE_PREFIX}{product_key}_*"):
        if image_path.suffix.lower() not in {".gif", ".jpg", ".jpeg", ".png"}:
            continue
        results.append(_local_image_result(product_key, image_path))

    results.sort(key=lambda item: item.get("time") or "", reverse=True)
    if limit is not None and limit > 0:
        return results[:limit]
    return results


def find_local_cma_image_product(product_key: str, time_text: str) -> Optional[Dict[str, Any]]:
    try:
        target_time = datetime.strptime(time_text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            target_time = datetime.strptime(time_text, "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise ValueError("time 参数格式错误，支持 YYYY-MM-DD HH:mm:ss 或 YYYYMMDDHHmmss") from exc

    target = target_time.strftime("%Y-%m-%d %H:%M:%S")
    for item in list_local_cma_image_products(product_key):
        if item.get("time") == target:
            return item
    return None


def list_cma_image_product_configs() -> List[Dict[str, str]]:
    return [
        {
            "product": product.key,
            "product_name": product.label,
            "description": product.description,
            "page_url": product.page_url,
        }
        for product in CMA_IMAGE_PRODUCTS.values()
    ]
