import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cartopy.crs as ccrs
import cinrad
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import NotFound

from reflectance.music.music_radar import _parse_front_time
from reflectance.music.precipitation import (
    get_precipitation_product,
    precipitation_bin_path,
)

logger = logging.getLogger(__name__)

PRECIPITATION_RENDER_DPI = 600


class _ScheduleRequest:
    def __init__(self, time_param: Optional[str] = None):
        self.query_params = {"time": time_param} if time_param else {}


def _precipitation_img_dir(product_key: str) -> Path:
    product = get_precipitation_product(product_key)
    return Path(settings.MEDIA_ROOT) / "precipitation" / product.key


def _time_to_cache_key(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def _cache_key_to_datetime(cache_key: str) -> Optional[datetime]:
    try:
        return datetime.strptime(cache_key, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _image_prefix(product_key: str) -> str:
    product = get_precipitation_product(product_key)
    return f"precipitation_{product.key}_"


def _build_image_url(product_key: str, image_filename: str) -> str:
    product = get_precipitation_product(product_key)
    media_url = settings.MEDIA_URL
    if not str(media_url).endswith("/"):
        media_url = f"{media_url}/"
    return f"{media_url}precipitation/{product.key}/{image_filename}"


def _response_time_from_meta(meta_path: Path, fallback_dt: datetime) -> str:
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            t = meta.get("time")
            if t:
                return str(t)
        except (OSError, json.JSONDecodeError):
            pass
    return fallback_dt.strftime("%Y-%m-%d %H:%M:%S")


def _local_image_result(product_key: str, image_path: Path, response_dt: datetime) -> Dict[str, Any]:
    image_filename = image_path.name
    meta_path = image_path.with_suffix(".json")
    return {
        "image_filename": image_filename,
        "image_path": str(image_path),
        "image_url": _build_image_url(product_key, image_filename),
        "response_time": _response_time_from_meta(meta_path, response_dt),
        "from_cache": True,
    }


def _image_time_from_path(product_key: str, png_path: Path) -> Optional[datetime]:
    meta_path = png_path.with_suffix(".json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            t = meta.get("time")
            if t:
                return _parse_front_time(str(t)).replace(tzinfo=None, microsecond=0)
        except (ValueError, OSError, json.JSONDecodeError):
            pass
    prefix = _image_prefix(product_key)
    return _cache_key_to_datetime(png_path.stem.replace(prefix, "", 1))


def get_precipitation_from_local(product_key: str, time_param: str) -> Dict[str, Any]:
    product = get_precipitation_product(product_key)
    req_dt = _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)
    img_dir = _precipitation_img_dir(product.key)
    if not img_dir.is_dir():
        raise NotFound(f"本地暂无{product.label}图片")

    prefix = _image_prefix(product.key)
    png_files = list(img_dir.glob(f"{prefix}*.png"))
    if not png_files:
        raise NotFound(f"本地暂无{product.label}图片")

    for png_path in png_files:
        file_dt = _image_time_from_path(product.key, png_path)
        if file_dt == req_dt:
            return _local_image_result(product.key, png_path, req_dt)

    exact_path = img_dir / f"{prefix}{_time_to_cache_key(req_dt)}.png"
    if exact_path.is_file():
        return _local_image_result(product.key, exact_path, req_dt)

    candidates = []
    for png_path in png_files:
        file_dt = _image_time_from_path(product.key, png_path)
        if file_dt is not None:
            candidates.append((abs(file_dt - req_dt), file_dt, png_path))

    if not candidates:
        raise NotFound(f"本地{product.label}图片缺少可识别的时次信息")

    _delta, file_dt, chosen_path = min(candidates, key=lambda item: item[0])
    logger.info(
        "请求时次 %s 无精确本地%s图片，返回最近时次 %s",
        req_dt.strftime("%Y-%m-%d %H:%M:%S"),
        product.label,
        file_dt.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return _local_image_result(product.key, chosen_path, file_dt)


def _data_for_plot(data):
    d = np.ma.masked_invalid(np.asarray(data, dtype=float))
    arr = np.where(d.mask, np.nan, d.filled(np.nan))
    return np.where(np.isfinite(arr) & (arr > 0), arr, np.nan)


def _extract_corners(f) -> Dict[str, Any]:
    min_lon = float(np.nanmin(f.lon))
    max_lon = float(np.nanmax(f.lon))
    min_lat = float(np.nanmin(f.lat))
    max_lat = float(np.nanmax(f.lat))
    return _extract_corners_from_bounds(min_lon, max_lon, min_lat, max_lat)


def _extract_corners_from_bounds(min_lon, max_lon, min_lat, max_lat) -> Dict[str, Any]:
    return {
        "left_bottom": {"lon": min_lon, "lat": min_lat},
        "right_bottom": {"lon": max_lon, "lat": min_lat},
        "right_top": {"lon": max_lon, "lat": max_lat},
        "left_top": {"lon": min_lon, "lat": max_lat},
    }


def align_to_six_minute_grid(dt: Optional[datetime] = None) -> datetime:
    if dt is None:
        dt = timezone.now()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    minute_bucket = (dt.minute // 6) * 6
    return dt.replace(minute=minute_bucket, second=0, microsecond=0)


def align_to_hour_grid(dt: Optional[datetime] = None) -> datetime:
    if dt is None:
        dt = timezone.now()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt.replace(minute=0, second=0, microsecond=0)


def _render_precipitation_png(file_path: Path, image_path: Path):
    f = cinrad.io.MocMosaic(str(file_path))
    data_plot = _data_for_plot(f.data)

    fig, ax = plt.subplots(
        figsize=(16, 12),
        subplot_kw={"projection": ccrs.PlateCarree()},
        facecolor="none",
    )
    ax.set_facecolor("none")
    fig.patch.set_facecolor("none")
    ax.patch.set_facecolor("none")
    ax.patch.set_alpha(0.0)
    ax.patch.set_visible(False)

    try:
        ax.background_patch.set_facecolor("none")
        ax.background_patch.set_alpha(0.0)
        ax.background_patch.set_visible(False)
        ax.outline_patch.set_visible(False)
    except AttributeError:
        pass

    cmap = plt.cm.turbo.copy()
    cmap.set_bad((0.0, 0.0, 0.0, 0.0))
    cmap.set_under((0.0, 0.0, 0.0, 0.0))

    ax.pcolormesh(
        f.lon,
        f.lat,
        np.ma.masked_invalid(data_plot),
        cmap=cmap,
        vmin=0,
        vmax=100,
        shading="auto",
        transform=ccrs.PlateCarree(),
        alpha=1.0,
    )

    min_lon = float(np.nanmin(f.lon))
    max_lon = float(np.nanmax(f.lon))
    min_lat = float(np.nanmin(f.lat))
    max_lat = float(np.nanmax(f.lat))
    corners = _extract_corners_from_bounds(min_lon, max_lon, min_lat, max_lat)

    ax.set_extent([min_lon, max_lon, min_lat, max_lat], crs=ccrs.PlateCarree())
    try:
        ax.background_patch.set_facecolor("none")
        ax.background_patch.set_alpha(0.0)
        ax.background_patch.set_visible(False)
        ax.outline_patch.set_visible(False)
    except AttributeError:
        pass

    ax.set_axis_off()
    plt.savefig(
        str(image_path),
        dpi=PRECIPITATION_RENDER_DPI,
        bbox_inches="tight",
        pad_inches=0,
        facecolor="none",
        transparent=True,
    )
    plt.close(fig)
    return corners


def render_precipitation_image(product_key: str, time_param: Optional[str] = None) -> Dict[str, Any]:
    product = get_precipitation_product(product_key)
    request = _ScheduleRequest(time_param)
    img_dir = _precipitation_img_dir(product.key)
    img_dir.mkdir(parents=True, exist_ok=True)

    with precipitation_bin_path(product.key, request) as (file_path, selected_time):
        cache_key = (
            selected_time.replace("-", "").replace(":", "").replace(" ", "")
            if selected_time
            else Path(file_path).stem
        )
        image_filename = f"{_image_prefix(product.key)}{cache_key}.png"
        image_path = img_dir / image_filename
        meta_path = image_path.with_suffix(".json")
        response_time = selected_time
        from_cache = False

        if image_path.exists():
            from_cache = True
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    response_time = meta.get("time", response_time) or response_time
                except (OSError, json.JSONDecodeError):
                    pass
            else:
                f = cinrad.io.MocMosaic(str(file_path))
                corners = _extract_corners(f)
                try:
                    meta_path.write_text(
                        json.dumps(
                            {
                                "time": response_time,
                                "product": product.key,
                                "data_code": product.data_code,
                                "corners": corners,
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
        else:
            corners = _render_precipitation_png(file_path, image_path)
            try:
                meta_path.write_text(
                    json.dumps(
                        {
                            "time": response_time,
                            "product": product.key,
                            "data_code": product.data_code,
                            "corners": corners,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass

    return {
        "image_filename": image_filename,
        "image_path": str(image_path),
        "image_url": _build_image_url(product.key, image_filename),
        "response_time": response_time,
        "from_cache": from_cache,
    }


def run_precipitation_schedule_once(product_key: str) -> None:
    product = get_precipitation_product(product_key)
    try:
        aligned = align_to_hour_grid() if product.key == "3h" else align_to_six_minute_grid()
        time_str = aligned.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{product.label}] 定时任务开始: 对齐时次={time_str}", flush=True)
        result = render_precipitation_image(product.key, time_str)
        msg = (
            f"{product.key} precipitation 定时任务完成: time={result.get('response_time')}, "
            f"file={result.get('image_filename')}, "
            f"cache_hit={result.get('from_cache')}, "
            f"path={result.get('image_path')}"
        )
        print(msg, flush=True)
        logger.info(msg)
    except Exception:
        logger.exception("%s定时任务执行失败", product.label)


def run_precipitation_1h_schedule_once() -> None:
    run_precipitation_schedule_once("1h")


def run_precipitation_3h_schedule_once() -> None:
    run_precipitation_schedule_once("3h")
