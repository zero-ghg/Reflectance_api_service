import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from django.conf import settings
from PIL import Image
from rest_framework.exceptions import NotFound

from reflectance.celery_beat.schedule_component import (
    align_to_six_minute_grid,
    get_reflectance_exact_from_local,
    render_reflectance_image,
)
from reflectance.music.music_radar import _parse_front_time

logger = logging.getLogger(__name__)

REFLECTANCE_NOWCAST_THRESHOLD_DBZ = 35.0
REFLECTANCE_NOWCAST_GRID_COLS = 96
REFLECTANCE_NOWCAST_HISTORY_COUNT = 4
REFLECTANCE_NOWCAST_INTERVAL_MINUTES = 6
REFLECTANCE_NOWCAST_MAX_CELLS_PER_LEAD = 360
DEFAULT_LEAD_MINUTES = (30, 60, 90)
DEFAULT_REFLECTANCE_CORNERS = {
    "left_bottom": {"lon": 73.0, "lat": 11.7},
    "right_bottom": {"lon": 135.0, "lat": 11.7},
    "right_top": {"lon": 135.0, "lat": 53.7},
    "left_top": {"lon": 73.0, "lat": 53.7},
}


def _reflectance_img_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / "reflectance"


def _load_meta(image_path: Path) -> Dict[str, Any]:
    meta_path = image_path.with_suffix(".json")
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("反射率元数据读取失败: %s", meta_path)
        return {}


def _image_time_from_path(image_path: Path, meta: Dict[str, Any]) -> Optional[datetime]:
    time_text = meta.get("time")
    if time_text:
        try:
            return _parse_front_time(str(time_text)).replace(tzinfo=None, microsecond=0)
        except ValueError:
            pass
    stem = image_path.stem.replace("reflectance_", "", 1)
    try:
        return datetime.strptime(stem, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _normalize_corners(corners: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not corners:
        return DEFAULT_REFLECTANCE_CORNERS
    try:
        required = ("left_bottom", "right_bottom", "right_top", "left_top")
        normalized = {}
        for key in required:
            point = corners[key]
            normalized[key] = {
                "lon": float(point["lon"]),
                "lat": float(point["lat"]),
            }
        return normalized
    except (KeyError, TypeError, ValueError):
        return DEFAULT_REFLECTANCE_CORNERS


def _bounds_from_corners(corners: Dict[str, Any]) -> Dict[str, float]:
    return {
        "left": float(corners["left_bottom"]["lon"]),
        "right": float(corners["right_bottom"]["lon"]),
        "bottom": float(corners["left_bottom"]["lat"]),
        "top": float(corners["left_top"]["lat"]),
    }


def _list_local_reflectance_frames(target_dt: datetime, history_count: int) -> List[Dict[str, Any]]:
    img_dir = _reflectance_img_dir()
    if not img_dir.is_dir():
        return []

    frames = []
    for image_path in img_dir.glob("reflectance_*.png"):
        meta = _load_meta(image_path)
        image_time = _image_time_from_path(image_path, meta)
        if image_time is None or image_time > target_dt:
            continue
        frames.append(
            {
                "image_path": image_path,
                "time": image_time,
                "corners": _normalize_corners(meta.get("corners")),
            }
        )

    frames.sort(key=lambda item: item["time"])
    return frames[-history_count:]


def _warm_recent_reflectance_frames(target_dt: datetime, history_count: int) -> None:
    for index in range(history_count):
        frame_dt = target_dt - timedelta(minutes=REFLECTANCE_NOWCAST_INTERVAL_MINUTES * index)
        time_text = frame_dt.strftime("%Y-%m-%d %H:%M:%S")
        try:
            get_reflectance_exact_from_local(time_text)
        except Exception:
            try:
                render_reflectance_image(time_text)
            except Exception:
                logger.exception("雷达反射率临近预警预热失败: %s", time_text)


def _jet_lookup() -> Tuple[np.ndarray, np.ndarray]:
    values = np.linspace(0, 70, 701, dtype=np.float32)
    colors = (plt.cm.jet(values / 70.0)[:, :3] * 255).astype(np.float32)
    return colors, values


def _grid_shape(corners: Dict[str, Any], grid_cols: int) -> Tuple[int, int]:
    bounds = _bounds_from_corners(corners)
    lon_span = max(0.01, bounds["right"] - bounds["left"])
    lat_span = max(0.01, bounds["top"] - bounds["bottom"])
    rows = int(round(grid_cols * lat_span / lon_span))
    return max(24, min(96, rows)), grid_cols


def _decode_reflectance_image(image_path: Path, corners: Dict[str, Any], grid_cols: int) -> np.ndarray:
    rows, cols = _grid_shape(corners, grid_cols)
    resample_box = getattr(getattr(Image, "Resampling", Image), "BOX")
    image = Image.open(image_path).convert("RGBA").resize((cols, rows), resample_box)
    arr = np.asarray(image, dtype=np.float32)
    alpha = arr[:, :, 3]
    valid = alpha > 12

    field = np.full((rows, cols), np.nan, dtype=np.float32)
    if not np.any(valid):
        return field

    colors, values = _jet_lookup()
    rgb = arr[:, :, :3][valid]
    distance = np.sum((rgb[:, None, :] - colors[None, :, :]) ** 2, axis=2)
    field[valid] = values[np.argmin(distance, axis=1)]
    return field


def _lon_lat_grids(corners: Dict[str, Any], rows: int, cols: int) -> Tuple[np.ndarray, np.ndarray]:
    bounds = _bounds_from_corners(corners)
    lon_values = bounds["left"] + (np.arange(cols) + 0.5) / cols * (bounds["right"] - bounds["left"])
    lat_values = bounds["top"] - (np.arange(rows) + 0.5) / rows * (bounds["top"] - bounds["bottom"])
    lon_grid, lat_grid = np.meshgrid(lon_values, lat_values)
    return lon_grid, lat_grid


def _weighted_centroid(field: np.ndarray, corners: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    mask = np.isfinite(field) & (field >= REFLECTANCE_NOWCAST_THRESHOLD_DBZ)
    if not np.any(mask):
        return None
    rows, cols = field.shape
    lon_grid, lat_grid = _lon_lat_grids(corners, rows, cols)
    weights = np.maximum(field - REFLECTANCE_NOWCAST_THRESHOLD_DBZ + 1, 1)
    weights = np.where(mask, weights, 0)
    total = float(np.sum(weights))
    if total <= 0:
        return None
    return (
        float(np.sum(lon_grid * weights) / total),
        float(np.sum(lat_grid * weights) / total),
    )


def _estimate_motion(frames: List[Dict[str, Any]], fields: List[np.ndarray]) -> Dict[str, Any]:
    latest_centroid = _weighted_centroid(fields[-1], frames[-1]["corners"]) if fields else None
    first_usable = None
    for index, field in enumerate(fields[:-1]):
        centroid = _weighted_centroid(field, frames[index]["corners"])
        if centroid:
            first_usable = (index, centroid)
            break

    if not latest_centroid or not first_usable:
        return {
            "available": False,
            "dlon_per_min": 0.0,
            "dlat_per_min": 0.0,
            "speed_kmh": 0.0,
            "direction": "stationary",
            "latest_centroid": latest_centroid,
        }

    start_index, start_centroid = first_usable
    minutes = max(1.0, (frames[-1]["time"] - frames[start_index]["time"]).total_seconds() / 60.0)
    dlon_per_min = (latest_centroid[0] - start_centroid[0]) / minutes
    dlat_per_min = (latest_centroid[1] - start_centroid[1]) / minutes
    avg_lat = (latest_centroid[1] + start_centroid[1]) / 2
    km_per_lon = 111.32 * max(0.25, np.cos(np.deg2rad(avg_lat)))
    speed_kmh = float(np.hypot(dlon_per_min * km_per_lon, dlat_per_min * 111.32) * 60)
    angle = (np.degrees(np.arctan2(dlon_per_min * km_per_lon, dlat_per_min * 111.32)) + 360) % 360
    direction = _direction_name(angle)
    return {
        "available": True,
        "dlon_per_min": round(float(dlon_per_min), 5),
        "dlat_per_min": round(float(dlat_per_min), 5),
        "speed_kmh": round(speed_kmh, 2),
        "direction": direction,
        "latest_centroid": {"lon": round(latest_centroid[0], 4), "lat": round(latest_centroid[1], 4)},
    }


def _direction_name(angle: float) -> str:
    names = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")
    return names[int((angle + 22.5) // 45) % 8]


def _risk_level(dbz: float) -> int:
    if dbz >= 55:
        return 3
    if dbz >= 45:
        return 2
    if dbz >= REFLECTANCE_NOWCAST_THRESHOLD_DBZ:
        return 1
    return 0


def _risk_probability(dbz: float, lead_minutes: int) -> int:
    raw = dbz * 1.35 - 20 - lead_minutes * 0.12
    return int(max(25, min(95, round(raw))))


def _iter_nowcast_cells(
    field: np.ndarray,
    corners: Dict[str, Any],
    motion: Dict[str, Any],
    lead_minutes: Iterable[int],
) -> List[Dict[str, Any]]:
    bounds = _bounds_from_corners(corners)
    rows, cols = field.shape
    lon_step = (bounds["right"] - bounds["left"]) / cols
    lat_step = (bounds["top"] - bounds["bottom"]) / rows
    source_mask = np.isfinite(field) & (field >= REFLECTANCE_NOWCAST_THRESHOLD_DBZ)
    source_indices = np.argwhere(source_mask)
    cells: List[Dict[str, Any]] = []

    for lead in lead_minutes:
        lead_cells = []
        shift_lon = float(motion.get("dlon_per_min", 0.0)) * lead
        shift_lat = float(motion.get("dlat_per_min", 0.0)) * lead
        for row, col in source_indices:
            dbz = float(field[row, col])
            level = _risk_level(dbz)
            if level <= 0:
                continue
            left = bounds["left"] + col * lon_step + shift_lon
            right = left + lon_step
            top = bounds["top"] - row * lat_step + shift_lat
            bottom = top - lat_step
            center_lon = (left + right) / 2
            center_lat = (top + bottom) / 2
            if right < bounds["left"] or left > bounds["right"] or top < bounds["bottom"] or bottom > bounds["top"]:
                continue
            lead_cells.append(
                {
                    "id": f"{lead}-{row}-{col}",
                    "lead_minutes": lead,
                    "level": level,
                    "probability": _risk_probability(dbz, lead),
                    "max_dbz": round(dbz, 1),
                    "center": {"lon": round(center_lon, 5), "lat": round(center_lat, 5)},
                    "bounds": {
                        "left": round(left, 5),
                        "right": round(right, 5),
                        "top": round(top, 5),
                        "bottom": round(bottom, 5),
                    },
                }
            )

        lead_cells.sort(key=lambda item: (item["level"], item["probability"], item["max_dbz"]), reverse=True)
        cells.extend(lead_cells[:REFLECTANCE_NOWCAST_MAX_CELLS_PER_LEAD])

    return cells


def _parse_lead_minutes(value: Optional[str]) -> List[int]:
    if not value:
        return list(DEFAULT_LEAD_MINUTES)
    result = []
    for item in str(value).split(","):
        try:
            minutes = int(item.strip())
        except ValueError:
            continue
        if 5 <= minutes <= 180:
            result.append(minutes)
    return result or list(DEFAULT_LEAD_MINUTES)


def _frame_payload(frame: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "time": frame["time"].strftime("%Y-%m-%d %H:%M:%S"),
        "image": frame["image_path"].name,
    }


def build_thunderstorm_nowcast(
    time_param: Optional[str] = None,
    history_count: int = REFLECTANCE_NOWCAST_HISTORY_COUNT,
    lead_minutes_param: Optional[str] = None,
) -> Dict[str, Any]:
    target_dt = (
        _parse_front_time(time_param).replace(tzinfo=None, microsecond=0)
        if time_param
        else align_to_six_minute_grid()
    )
    history_count = max(2, min(8, int(history_count or REFLECTANCE_NOWCAST_HISTORY_COUNT)))
    lead_minutes = _parse_lead_minutes(lead_minutes_param)

    frames = _list_local_reflectance_frames(target_dt, history_count)
    if len(frames) < 2:
        _warm_recent_reflectance_frames(target_dt, history_count)
        frames = _list_local_reflectance_frames(target_dt, history_count)

    if len(frames) < 2:
        raise NotFound("本地反射率图片不足，无法进行雷雨临近预警研判")

    latest_corners = frames[-1]["corners"]
    fields = [
        _decode_reflectance_image(frame["image_path"], latest_corners, REFLECTANCE_NOWCAST_GRID_COLS)
        for frame in frames
    ]
    latest_field = fields[-1]
    valid_latest = latest_field[np.isfinite(latest_field)]
    max_dbz = float(np.max(valid_latest)) if valid_latest.size else 0.0
    motion = _estimate_motion(frames, fields)
    cells = _iter_nowcast_cells(latest_field, latest_corners, motion, lead_minutes)
    max_level = max([cell["level"] for cell in cells], default=0)

    return {
        "time": frames[-1]["time"].strftime("%Y-%m-%d %H:%M:%S"),
        "target_time": target_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "corners": latest_corners,
        "source_frames": [_frame_payload(frame) for frame in frames],
        "motion": motion,
        "summary": {
            "max_level": max_level,
            "max_dbz": round(max_dbz, 1),
            "risk_cell_count": len(cells),
            "lead_minutes": lead_minutes,
            "threshold_dbz": REFLECTANCE_NOWCAST_THRESHOLD_DBZ,
        },
        "cells": cells,
    }
