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
from PIL import Image
from rest_framework.exceptions import NotFound

from reflectance.music.music_radar import _parse_front_time, radar_bin_path

logger = logging.getLogger(__name__)

REFLECTANCE_RENDER_DPI = 600
REFLECTANCE_OPACITY = 0.8


class _ScheduleRequest:
    """供定时任务调用 radar_bin_path 时模拟 DRF 请求的 query_params。"""

    def __init__(self, time_param: Optional[str] = None):
        self.query_params = {"time": time_param} if time_param else {}


def _data_for_plot(data):
    d = np.ma.masked_invalid(np.asarray(data, dtype=float))
    return np.where(d.mask, np.nan, d.filled(np.nan))


def _write_reflectance_png_with_alpha(src_path: Path, dest_path: Path) -> None:
    img = Image.open(src_path).convert("RGBA")
    arr = np.asarray(img).copy()
    alpha = arr[:, :, 3].astype(np.float32)
    visible = alpha > 0
    alpha[visible] = np.clip(alpha[visible] * REFLECTANCE_OPACITY, 0, 255)
    arr[:, :, 3] = alpha.astype(np.uint8)
    Image.fromarray(arr, mode="RGBA").save(dest_path)


def _reflectance_img_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / "reflectance"


def _time_to_cache_key(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def _cache_key_to_datetime(cache_key: str) -> Optional[datetime]:
    try:
        return datetime.strptime(cache_key, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _build_image_url(image_filename: str) -> str:
    media_url = settings.MEDIA_URL
    if not str(media_url).endswith("/"):
        media_url = f"{media_url}/"
    return f"{media_url}reflectance/{image_filename}"


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


def _corners_from_meta(meta_path: Path):
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return meta.get("corners")
        except (OSError, json.JSONDecodeError):
            pass
    return None


def _local_image_result(image_path: Path, response_dt: datetime) -> Dict[str, Any]:
    image_filename = image_path.name
    meta_path = image_path.with_suffix(".json")
    return {
        "image_filename": image_filename,
        "image_path": str(image_path),
        "image_url": _build_image_url(image_filename),
        "response_time": _response_time_from_meta(meta_path, response_dt),
        "corners": _corners_from_meta(meta_path),
        "from_cache": True,
    }


def _image_time_from_path(png_path: Path) -> Optional[datetime]:
    """从 json 元数据或文件名解析图片时次。"""
    meta_path = png_path.with_suffix(".json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            t = meta.get("time")
            if t:
                return _parse_front_time(str(t)).replace(tzinfo=None, microsecond=0)
        except (ValueError, OSError, json.JSONDecodeError):
            pass
    return _cache_key_to_datetime(png_path.stem.replace("reflectance_", "", 1))


def get_reflectance_from_local(time_param: str) -> Dict[str, Any]:
    """
    仅从本地 apps/img/reflectance 读取 PNG，不调用 MUSIC、不渲染。
    1. 按前端 time 在本地精确匹配；
    2. 若无，取与请求时次时间差最小的一张。
    """
    req_dt = _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)
    img_dir = _reflectance_img_dir()
    if not img_dir.is_dir():
        raise NotFound("本地暂无反射率图片")

    png_files = list(img_dir.glob("reflectance_*.png"))
    if not png_files:
        raise NotFound("本地暂无反射率图片")

    # 1. 精确匹配（元数据时次或文件名时次与请求一致）
    for png_path in png_files:
        file_dt = _image_time_from_path(png_path)
        if file_dt == req_dt:
            return _local_image_result(png_path, req_dt)

    exact_path = img_dir / f"reflectance_{_time_to_cache_key(req_dt)}.png"
    if exact_path.is_file():
        return _local_image_result(exact_path, req_dt)

    # 2. 未精确命中时，取离请求时刻最近的一张（可早于或晚于请求时刻）
    candidates = []
    for png_path in png_files:
        file_dt = _image_time_from_path(png_path)
        if file_dt is not None and file_dt <= req_dt:
            candidates.append((file_dt, png_path))

    if not candidates:
        raise NotFound("本地反射率图片缺少可识别的时次信息")

    file_dt, chosen_path = max(candidates, key=lambda item: item[0])
    logger.info(
        "请求时次 %s 无精确本地图片，返回最近时次 %s",
        req_dt.strftime("%Y-%m-%d %H:%M:%S"),
        file_dt.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return _local_image_result(chosen_path, file_dt)


def get_reflectance_exact_from_local(time_param: str) -> Dict[str, Any]:
    req_dt = _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)
    img_dir = _reflectance_img_dir()
    if not img_dir.is_dir():
        raise NotFound("本地暂无反射率图片")

    png_files = list(img_dir.glob("reflectance_*.png"))
    if not png_files:
        raise NotFound("本地暂无反射率图片")

    for png_path in png_files:
        file_dt = _image_time_from_path(png_path)
        if file_dt == req_dt:
            return _local_image_result(png_path, req_dt)

    exact_path = img_dir / f"reflectance_{_time_to_cache_key(req_dt)}.png"
    if exact_path.is_file():
        return _local_image_result(exact_path, req_dt)

    raise NotFound("本地暂无指定时次的反射率图片")


def align_to_six_minute_grid(dt: Optional[datetime] = None) -> datetime:
    """对齐到整点起的 6 分钟网格（00、06、12…54 分）。"""
    if dt is None:
        dt = timezone.now()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    minute_bucket = (dt.minute // 6) * 6
    return dt.replace(minute=minute_bucket, second=0, microsecond=0)


def render_reflectance_image(time_param: Optional[str] = None) -> Dict[str, Any]:
    """
    从 MUSIC 拉取 bin 并渲染到 MEDIA_ROOT/reflectance（供 Celery 定时任务调用）。

    返回:
        dict: image_filename, image_url, response_time, from_cache
    """
    request = _ScheduleRequest(time_param)
    img_dir = _reflectance_img_dir()
    img_dir.mkdir(parents=True, exist_ok=True)

    with radar_bin_path(request) as (file_path, selected_time):
        cache_key = (
            selected_time.replace("-", "").replace(":", "").replace(" ", "")
            if selected_time
            else Path(file_path).stem
        )
        image_filename = f"reflectance_{cache_key}.png"
        image_path = img_dir / image_filename
        meta_path = image_path.with_suffix(".json")
        response_time = selected_time
        from_cache = False

        if Path(file_path).suffix.lower() in {".png", ".jpg", ".jpeg"}:
            from_cache = image_path.exists()
            _write_reflectance_png_with_alpha(file_path, image_path)
            try:
                meta_path.write_text(
                    json.dumps({"time": response_time, "corners": None}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                pass
            return {
                "image_filename": image_filename,
                "image_path": str(image_path),
                "image_url": _build_image_url(image_filename),
                "response_time": response_time,
                "corners": None,
                "from_cache": from_cache,
            }

        corners = None
        if image_path.exists():
            from_cache = True
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    response_time = meta.get("time", response_time) or response_time
                    corners = meta.get("corners")
                except (OSError, json.JSONDecodeError):
                    pass
            if not meta_path.exists():
                f = cinrad.io.MocMosaic(str(file_path))
                corners = _extract_corners(f)
                try:
                    meta_path.write_text(
                        json.dumps({"time": response_time, "corners": corners}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
        else:
            f = cinrad.io.MocMosaic(str(file_path))
            data_transparent = _data_for_plot(f.data)
            arr = np.asarray(data_transparent, dtype=float)
            data_plot = np.where(np.isfinite(arr) & (arr < 1), np.nan, arr)

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

            cmap = plt.cm.jet.copy()
            cmap.set_bad((0.0, 0.0, 0.0, 0.0))

            ax.pcolormesh(
                f.lon,
                f.lat,
                np.ma.masked_invalid(data_plot),
                cmap=cmap,
                vmin=0,
                vmax=70,
                shading="auto",
                transform=ccrs.PlateCarree(),
                alpha=REFLECTANCE_OPACITY,
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
                dpi=REFLECTANCE_RENDER_DPI,
                bbox_inches="tight",
                pad_inches=0,
                facecolor="none",
                transparent=True,
            )
            plt.close(fig)
            try:
                meta_path.write_text(
                    json.dumps({"time": response_time, "corners": corners}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                pass

    return {
        "image_filename": image_filename,
        "image_path": str(image_path),
        "image_url": _build_image_url(image_filename),
        "response_time": response_time,
        "corners": corners,
        "from_cache": from_cache,
    }


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


def run_reflectance_schedule_once() -> None:
    """执行一次反射率预渲染：对齐 6 分钟时次，拉取最新雷达并落盘。"""
    try:
        aligned = align_to_six_minute_grid()
        time_str = aligned.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[反射率] 定时任务开始: 对齐时次={time_str}",
            flush=True,
        )
        result = render_reflectance_image(time_str)
        msg = (
            f"reflectance 定时任务完成: time={result.get('response_time')}, "
            f"file={result.get('image_filename')}, "
            f"cache_hit={result.get('from_cache')}, "
            f"path={result.get('image_path')}"
        )
        print(msg, flush=True)
        logger.info(msg)
    except Exception:
        logger.exception("反射率定时任务执行失败")
