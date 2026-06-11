from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
import logging
import os
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from lightning_warning.celery_beat.schedule_component import query_by_time, query_nearest_by_time

logger = logging.getLogger(__name__)

# PostgreSQL 数据库配置，可通过环境变量覆盖
PG_CONFIG = {
    "host": os.getenv("LIGHTNING_PG_HOST", "192.168.30.91"),
    "port": int(os.getenv("LIGHTNING_PG_PORT", "5432")),
    "database": os.getenv("LIGHTNING_PG_DATABASE", "networking"),
    "user": os.getenv("LIGHTNING_PG_USER", "postgres"),
    "password": os.getenv("LIGHTNING_PG_PASSWORD", "ADMIN@12344321"),
    "options": os.getenv("LIGHTNING_PG_OPTIONS", "-c search_path=atmo,public"),
}

MIN_VALID_SAMPLES = int(os.getenv("LIGHTNING_WARNING_MIN_VALID_SAMPLES", "30"))
MAX_ANALYSIS_POINTS = int(os.getenv("LIGHTNING_WARNING_MAX_ANALYSIS_POINTS", "1800"))
RECENT_SECONDS = int(os.getenv("LIGHTNING_WARNING_RECENT_SECONDS", "60"))
MID_WINDOW_SECONDS = int(os.getenv("LIGHTNING_WARNING_MID_WINDOW_SECONDS", "300"))


class Detail_Warning(APIView):
    @staticmethod
    def _beijing_tz() -> dt_timezone:
        return dt_timezone(timedelta(hours=8))  # 返回北京时区（UTC+8）

    def _format_api_time(self, end_dt) -> str:
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=self._beijing_tz())
        else:
            end_dt = end_dt.astimezone(self._beijing_tz())
        return end_dt.strftime("%Y-%m-%d %H:%M:%S")

    def predict_lightning_by_electric_field(
            self,
            data: List[Dict[str, Any]],
            field_key: str = "mesaure_value",
            time_key: str = "time",
            unit: str = "kV/m"
    ) -> Dict[str, Any]:
        """
        根据电场数据预测雷电预警等级

        参数:
            data: 电场监测数据列表
            field_key: 电场值字段名
            time_key: 时间字段名
            unit: 单位（kV/m 或 V/m）

        返回:
            预测结果字典，包含预警等级、概率、分数等信息
        """
        if not data:
            return self._empty_result("未传入电场数据。")

        fields = []
        times = []

        for item in data:
            try:
                value = float(item[field_key])
                if not np.isfinite(value):
                    continue
                if unit == "V/m":
                    value = value / 1000.0
                fields.append(value)
                times.append(self._parse_time_value(item.get(time_key)))
            except Exception:
                continue

        if len(fields) < MIN_VALID_SAMPLES:
            return self._empty_result("有效电场数据不足，无法进行预警判断。")

        fields, times = self._sort_series_by_time(np.array(fields, dtype=float), times)
        fields = fields[-MAX_ANALYSIS_POINTS:]
        times = times[-MAX_ANALYSIS_POINTS:]

        features = self._calculate_electric_field_features(fields, times)
        score_detail = self._calculate_warning_score(features)
        score = score_detail["total_score"]
        probability = round(score / 100.0, 2)

        if score < 20:
            warning_level = 0
            warning_name = "正常"
            message = "当前电场整体较平稳，雷电风险较低。"
        elif score < 45:
            warning_level = 1
            warning_name = "关注"
            message = "电场出现一定增强或波动，建议持续关注。"
        elif score < 75:
            warning_level = 2
            warning_name = "警戒"
            message = "电场强度或变化率明显升高，存在雷电活动风险。"
        else:
            warning_level = 3
            warning_name = "高危"
            message = "电场持续异常或剧烈变化，雷电风险较高，建议采取防雷措施。"

        return {
            "warning_level": warning_level,
            "warning_name": warning_name,
            "probability": probability,
            "score": score,
            "message": message,
            "features": features,
            "score_detail": score_detail,
            "radius": {
                "core_radius_km": 5,
                "reference_radius_km": 10,
                "max_reference_radius_km": 20,
                "description": "单站电场仪建议以5km作为核心预警范围，10km作为参考预警范围，20km以内作为最大参考范围。"
            }
        }

    def _parse_time_value(self, value) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return self._normalize_pg_datetime(value)
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if not timezone.is_naive(parsed):
            parsed = parsed.astimezone(self._beijing_tz()).replace(tzinfo=None)
        return parsed

    @staticmethod
    def _sort_series_by_time(fields: np.ndarray, times: List[Optional[datetime]]) -> Tuple[np.ndarray, List[Optional[datetime]]]:
        sortable = [
            (idx, fields[idx], times[idx])
            for idx in range(len(fields))
            if idx < len(times) and times[idx] is not None
        ]
        if len(sortable) < max(3, int(len(fields) * 0.6)):
            return fields, times
        sortable.sort(key=lambda item: item[2])
        return (
            np.array([item[1] for item in sortable], dtype=float),
            [item[2] for item in sortable],
        )

    @staticmethod
    def _slice_by_seconds(
            fields: np.ndarray,
            times: Optional[List[Optional[datetime]]],
            seconds: int,
            fallback_count: int,
    ) -> np.ndarray:
        if len(fields) == 0:
            return fields
        if times and len(times) == len(fields) and times[-1] is not None:
            latest_time = times[-1]
            start_time = latest_time - timedelta(seconds=seconds)
            mask = np.array(
                [t is not None and t >= start_time for t in times],
                dtype=bool,
            )
            sliced = fields[mask]
            if sliced.size > 0:
                return sliced
        return fields[-fallback_count:] if len(fields) >= fallback_count else fields

    @staticmethod
    def _safe_percentile(values: np.ndarray, percentile: float) -> float:
        if values.size == 0:
            return 0.0
        return float(np.percentile(values, percentile))

    @staticmethod
    def _median_interval_seconds(times: Optional[List[Optional[datetime]]]) -> Optional[float]:
        if not times:
            return None
        valid_times = [t for t in times if t is not None]
        if len(valid_times) < 2:
            return None
        diffs = [
            (valid_times[i] - valid_times[i - 1]).total_seconds()
            for i in range(1, len(valid_times))
            if valid_times[i] >= valid_times[i - 1]
        ]
        if not diffs:
            return None
        return float(np.median(diffs))

    @staticmethod
    def _coverage_minutes(times: Optional[List[Optional[datetime]]]) -> Optional[float]:
        if not times:
            return None
        valid_times = [t for t in times if t is not None]
        if len(valid_times) < 2:
            return None
        return round((valid_times[-1] - valid_times[0]).total_seconds() / 60.0, 2)

    def _calculate_electric_field_features(
            self,
            fields: np.ndarray,
            times: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        计算电场特征指标

        参数:
            fields: 电场值数组
            times: 时间列表

        返回:
            特征字典
        """
        recent_60 = self._slice_by_seconds(fields, times, RECENT_SECONDS, 60)
        recent_5min = self._slice_by_seconds(fields, times, MID_WINDOW_SECONDS, 300)

        abs_fields = np.abs(fields)
        recent_60_abs = np.abs(recent_60)
        recent_5min_abs = np.abs(recent_5min)
        recent_30_abs = recent_60_abs[-30:] if len(recent_60_abs) >= 30 else recent_60_abs

        current_e = fields[-1]
        current_abs_e = abs(current_e)

        mean_abs_window = float(np.mean(abs_fields))
        max_abs_window = float(np.max(abs_fields))
        p95_abs_window = self._safe_percentile(abs_fields, 95)
        std_abs_window = float(np.std(abs_fields))

        mean_abs_5min = float(np.mean(recent_5min_abs))
        max_abs_5min = float(np.max(recent_5min_abs))
        p95_abs_5min = self._safe_percentile(recent_5min_abs, 95)
        std_abs_5min = float(np.std(recent_5min_abs))

        mean_abs_60s = float(np.mean(recent_60_abs))
        max_abs_60s = float(np.max(recent_60_abs))
        p95_abs_60s = self._safe_percentile(recent_60_abs, 95)
        std_abs_60s = float(np.std(recent_60_abs))

        diff_60 = np.diff(recent_60)
        abs_diff_60 = np.abs(diff_60)
        max_change_60s = float(np.max(abs_diff_60)) if abs_diff_60.size > 0 else 0.0
        p95_change_60s = self._safe_percentile(abs_diff_60, 95)
        mean_change_60s = float(np.mean(abs_diff_60)) if abs_diff_60.size > 0 else 0.0

        diff_5min = np.diff(recent_5min)
        abs_diff_5min = np.abs(diff_5min)
        max_change_5min = float(np.max(abs_diff_5min)) if abs_diff_5min.size > 0 else 0.0
        p95_change_5min = self._safe_percentile(abs_diff_5min, 95)
        mean_change_5min = float(np.mean(abs_diff_5min)) if abs_diff_5min.size > 0 else 0.0

        sign_changes_60s = self._count_sign_changes(recent_60)
        sign_changes_5min = self._count_sign_changes(recent_5min)
        sign_changes_window = self._count_sign_changes(fields)

        high_field_duration_30s = int(np.sum(recent_30_abs >= 5.0))
        high_field_duration_60s = int(np.sum(recent_60_abs >= 5.0))
        high_field_duration_5min = int(np.sum(recent_5min_abs >= 5.0))
        high_field_ratio_5min = float(high_field_duration_5min / len(recent_5min_abs)) if len(recent_5min_abs) else 0.0
        high_field_ratio_window = float(np.sum(abs_fields >= 5.0) / len(abs_fields)) if len(abs_fields) else 0.0

        trend_slope_60s = self._calculate_trend_slope(recent_60)
        trend_slope_5min = self._calculate_trend_slope(recent_5min)
        trend_slope_window = self._calculate_trend_slope(fields)

        latest_time = times[-1] if times else None
        coverage_minutes = self._coverage_minutes(times)
        sampling_interval_seconds = self._median_interval_seconds(times)

        return {
            "latest_time": str(latest_time) if latest_time else None,
            "data_count": int(len(fields)),
            "recent_60s_count": int(len(recent_60)),
            "recent_5min_count": int(len(recent_5min)),
            "coverage_minutes": coverage_minutes,
            "sampling_interval_seconds": round(sampling_interval_seconds, 2) if sampling_interval_seconds else None,
            "current_e": round(float(current_e), 4),
            "current_abs_e": round(float(current_abs_e), 4),
            "mean_abs_window": round(mean_abs_window, 4),
            "max_abs_window": round(max_abs_window, 4),
            "p95_abs_window": round(p95_abs_window, 4),
            "std_abs_window": round(std_abs_window, 4),
            "mean_abs_5min": round(mean_abs_5min, 4),
            "max_abs_5min": round(max_abs_5min, 4),
            "p95_abs_5min": round(p95_abs_5min, 4),
            "std_abs_5min": round(std_abs_5min, 4),
            "mean_abs_60s": round(mean_abs_60s, 4),
            "max_abs_60s": round(max_abs_60s, 4),
            "p95_abs_60s": round(p95_abs_60s, 4),
            "std_abs_60s": round(std_abs_60s, 4),
            "max_change_5min": round(max_change_5min, 4),
            "p95_change_5min": round(p95_change_5min, 4),
            "mean_change_5min": round(mean_change_5min, 4),
            "max_change_60s": round(max_change_60s, 4),
            "p95_change_60s": round(p95_change_60s, 4),
            "mean_change_60s": round(mean_change_60s, 4),
            "sign_changes_5min": int(sign_changes_5min),
            "sign_changes_60s": int(sign_changes_60s),
            "sign_changes_window": int(sign_changes_window),
            "high_field_duration_30s": int(high_field_duration_30s),
            "high_field_duration_60s": int(high_field_duration_60s),
            "high_field_duration_5min": int(high_field_duration_5min),
            "high_field_ratio_5min": round(high_field_ratio_5min, 4),
            "high_field_ratio_window": round(high_field_ratio_window, 4),
            "trend_slope_60s": round(float(trend_slope_60s), 4),
            "trend_slope_5min": round(float(trend_slope_5min), 4),
            "trend_slope_window": round(float(trend_slope_window), 4),
        }

    def _calculate_warning_score(self, features: Dict[str, Any]) -> Dict[str, int]:
        """
        根据电场特征计算预警分数

        参数:
            features: 特征字典

        返回:
            分数详情字典
        """
        score_detail = {}
        mean_abs_60s = features["mean_abs_60s"]
        max_abs_60s = features["max_abs_60s"]
        p95_abs_60s = features.get("p95_abs_60s", max_abs_60s)
        mean_abs_5min = features["mean_abs_5min"]
        p95_abs_5min = features.get("p95_abs_5min", features.get("max_abs_5min", 0))
        mean_abs_window = features.get("mean_abs_window", mean_abs_5min)
        p95_abs_window = features.get("p95_abs_window", p95_abs_5min)
        max_change_60s = features["max_change_60s"]
        p95_change_60s = features.get("p95_change_60s", max_change_60s)
        mean_change_60s = features["mean_change_60s"]
        sign_changes_60s = features["sign_changes_60s"]
        high_field_duration_30s = features["high_field_duration_30s"]
        high_field_duration_60s = features["high_field_duration_60s"]
        high_field_ratio_5min = features.get("high_field_ratio_5min", 0)
        high_field_ratio_window = features.get("high_field_ratio_window", 0)
        trend_slope_60s = abs(features["trend_slope_60s"])
        trend_slope_window = abs(features.get("trend_slope_window", 0))

        if mean_abs_60s >= 8:
            mean_field_score = 35
        elif mean_abs_60s >= 5:
            mean_field_score = 26
        elif mean_abs_60s >= 2:
            mean_field_score = 12
        else:
            mean_field_score = 0
        score_detail["mean_field_score"] = mean_field_score

        if p95_abs_60s >= 10 or max_abs_60s >= 12:
            max_field_score = 20
        elif p95_abs_60s >= 7 or max_abs_60s >= 9:
            max_field_score = 15
        elif p95_abs_60s >= 4 or max_abs_60s >= 6:
            max_field_score = 8
        else:
            max_field_score = 0
        score_detail["max_field_score"] = max_field_score

        if mean_abs_5min >= 5 or p95_abs_5min >= 8:
            mean_5min_score = 10
        elif mean_abs_5min >= 2 or p95_abs_5min >= 4:
            mean_5min_score = 5
        else:
            mean_5min_score = 0
        score_detail["mean_5min_score"] = mean_5min_score

        if p95_change_60s >= 3 or max_change_60s >= 4:
            change_score = 20
        elif p95_change_60s >= 1.5 or max_change_60s >= 2.5:
            change_score = 14
        elif p95_change_60s >= 0.8 or max_change_60s >= 1.2:
            change_score = 7
        else:
            change_score = 0
        score_detail["change_score"] = change_score

        if mean_change_60s >= 1.0:
            mean_change_score = 5
        elif mean_change_60s >= 0.5:
            mean_change_score = 3
        else:
            mean_change_score = 0
        score_detail["mean_change_score"] = mean_change_score

        if sign_changes_60s >= 3:
            sign_change_score = 5
        elif sign_changes_60s >= 1:
            sign_change_score = 3
        else:
            sign_change_score = 0
        score_detail["sign_change_score"] = sign_change_score

        if high_field_ratio_5min >= 0.7 or high_field_duration_60s >= 40:
            duration_score = 10
        elif high_field_ratio_5min >= 0.4 or high_field_duration_30s >= 20:
            duration_score = 8
        elif high_field_ratio_5min >= 0.2 or high_field_duration_30s >= 10:
            duration_score = 5
        else:
            duration_score = 0
        score_detail["duration_score"] = duration_score

        if trend_slope_60s >= 0.08 or trend_slope_window >= 0.04:
            trend_score = 5
        elif trend_slope_60s >= 0.04 or trend_slope_window >= 0.02:
            trend_score = 3
        else:
            trend_score = 0
        score_detail["trend_score"] = trend_score

        if (mean_abs_window >= 5 and high_field_ratio_window >= 0.25) or p95_abs_window >= 8:
            sustained_score = 10
        elif mean_abs_window >= 2 or p95_abs_window >= 5:
            sustained_score = 6
        elif p95_abs_window >= 3:
            sustained_score = 3
        else:
            sustained_score = 0
        score_detail["sustained_score"] = sustained_score

        total_score = sum(score_detail.values())
        score_detail["total_score"] = min(int(total_score), 100)
        return score_detail

    def _count_sign_changes(self, values: np.ndarray) -> int:
        """计算符号变化次数"""
        signs = np.sign(values)
        signs = signs[signs != 0]
        if len(signs) < 2:
            return 0
        return int(np.sum(signs[1:] * signs[:-1] < 0))

    def _calculate_trend_slope(self, values: np.ndarray) -> float:
        """计算趋势斜率"""
        if len(values) < 2:
            return 0.0
        x = np.arange(len(values))
        y = values
        try:
            slope = np.polyfit(x, y, 1)[0]
            return float(slope)
        except Exception:
            return 0.0

    def _empty_result(self, message: str) -> Dict[str, Any]:
        """返回空结果"""
        return {
            "warning_level": 0,
            "warning_name": "数据不足",
            "probability": 0.0,
            "score": 0,
            "message": message,
            "features": None,
            "score_detail": None,
            "radius": {
                "core_radius_km": 5,
                "reference_radius_km": 10,
                "max_reference_radius_km": 20
            }
        }

    @staticmethod
    def _stat_int_scaled(value, unit: str) -> int:
        if value is None:  # 如果值为None
            return 0  # 返回0
        v = float(value)  # 转换为浮点数
        if unit == "V/m":  # 如果单位是V/m
            v = v / 1000.0  # 转换为kV/m
        return int(round(v))  # 四舍五入后转为整数返回

    def _fetch_pg_data(self, start_dt, end_dt):
        """
        直接从 PostgreSQL 查询电场监测数据

        参数:
            start_dt: 开始时间
            end_dt: 结束时间

        返回:
            列表，包含所有设备的数据记录
        """
        try:
            # 建立 PostgreSQL 连接
            conn = psycopg2.connect(**PG_CONFIG)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 查询SQL
            sql = """
                  SELECT device_id, time, mesaure_value, avg_value, rate, warn
                  FROM t_atmo_data
                  WHERE time >= %s \
                    AND time <= %s
                  ORDER BY device_id, time \
                  """

            cursor.execute(sql, (start_dt, end_dt))
            rows = cursor.fetchall()

            # 转换为字典列表
            result = [dict(row) for row in rows]

            cursor.close()
            conn.close()

            logger.info(f"从 PostgreSQL 查询到 {len(result)} 条数据")
            return result

        except Exception as e:
            logger.exception(f"PostgreSQL 查询失败: {e}")
            return []

    @staticmethod
    def _normalize_pg_datetime(value) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(Detail_Warning._beijing_tz()).replace(tzinfo=None)
        return value

    def _find_nearest_pg_end_time_before(self, query_dt) -> Optional[datetime]:
        """查询不晚于 query_dt 的最近一条监测数据时间（PG 最新时次）。"""
        try:
            conn = psycopg2.connect(**PG_CONFIG)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT MAX(time) AS latest_time FROM t_atmo_data WHERE time <= %s",
                (query_dt,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return self._normalize_pg_datetime(row.get("latest_time") if row else None)
        except Exception as e:
            logger.exception(f"PostgreSQL 查询最近时次失败: {e}")
            return None

    def _fetch_device_config_map(self) -> Dict[int, Dict[str, Any]]:
        """从 PostgreSQL 设备配置表查询 device_id -> 设备信息映射。"""
        try:
            conn = psycopg2.connect(**PG_CONFIG)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT id, device_name, lng, lat FROM t_atmo_config_tj"
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            result: Dict[int, Dict[str, Any]] = {}
            for row in rows:
                if row.get("id") is None:
                    continue
                device_pk = int(row["id"])
                lng = row.get("lng")
                lat = row.get("lat")
                result[device_pk] = {
                    "device_name": row.get("device_name") or "",
                    "lng": float(lng) if lng is not None else None,
                    "lat": float(lat) if lat is not None else None,
                }
            return result
        except Exception as e:
            logger.exception(f"查询设备配置失败: {e}")
            return {}

    def _build_warning_list(self, start_dt, end_dt, field_key: str, unit: str) -> List[Dict[str, Any]]:
        time_key = "time"  # 时间字段键名

        # 从 PostgreSQL 直接查询数据
        raw_rows = self._fetch_pg_data(start_dt, end_dt)

        if not raw_rows:
            logger.warning(f"时间窗口 [{start_dt}, {end_dt}] 内无数据")
            return []

        device_config_map = self._fetch_device_config_map()

        grouped_data: Dict[int, List[Dict[str, Any]]] = defaultdict(list)  # 创建设备数据分组字典
        device_stats: Dict[int, Dict[str, Any]] = {}

        for r in raw_rows:  # 遍历原始数据行
            if r.get("device_id") is None:
                continue
            device_pk = int(r["device_id"])
            grouped_data[device_pk].append(r)

            val = r.get(field_key)
            if val is None:
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(v):
                continue

            if device_pk not in device_stats:
                device_stats[device_pk] = {"max_val": v, "min_val": v, "sum": v, "cnt": 1}
            else:
                st = device_stats[device_pk]
                st["max_val"] = max(st["max_val"], v)
                st["min_val"] = min(st["min_val"], v)
                st["sum"] += v
                st["cnt"] += 1

        warning_list: List[Dict[str, Any]] = []  # 创建预警列表
        for device_pk in sorted(device_stats.keys()):  # 遍历每个设备的统计行
            st = device_stats[device_pk]
            row = {
                "device_id": device_pk,
                "max_val": st["max_val"],
                "min_val": st["min_val"],
                "avg_val": st["sum"] / st["cnt"] if st["cnt"] else 0,
            }
            ser = sorted(
                grouped_data.get(device_pk, []),
                key=lambda item: self._parse_time_value(item.get(time_key)) or datetime.min,
            )
            pred = self.predict_lightning_by_electric_field(  # 调用雷电预测方法
                data=ser,  # 传入设备数据序列
                field_key=field_key,  # 电场字段名
                time_key=time_key,  # 时间字段名
                unit=unit,  # 单位
            )
            wtype = int(pred.get("warning_level", 0))  # 获取预警等级
            cfg = device_config_map.get(device_pk, {})
            warning_list.append(  # 添加到预警列表
                {
                    "device_id": int(device_pk),  # 设备ID
                    "device_name": cfg.get("device_name", ""),
                    "lng": cfg.get("lng"),
                    "lat": cfg.get("lat"),
                    "type": wtype,  # 预警类型
                    "max_val": self._stat_int_scaled(row["max_val"], unit),  # 缩放后的最大值
                    "min_val": self._stat_int_scaled(row["min_val"], unit),  # 缩放后的最小值
                    "avg_val": self._stat_int_scaled(row["avg_val"], unit),  # 缩放后的平均值
                }
            )
        return warning_list  # 返回预警列表

    def get(self, request):
        """获取雷电预警结果"""
        time_str = request.query_params.get("end_time")
        if not time_str:
            return Response({"code": 400, "msg": "缺少参数end_time"})

        query_dt = parse_datetime(str(time_str))
        if query_dt is None:
            return Response(
                {"code": 400,"msg": "时间格式错误，请使用 ISO8601，例如 2026-05-10T12:06:00"})

        # 如果带有时区，转换为北京时间后移除时区信息（naive datetime）
        if not timezone.is_naive(query_dt):
            query_dt = query_dt.astimezone(self._beijing_tz()).replace(tzinfo=None)

        # 1. 先用前端传入的 end_time 查 MySQL 缓存
        warning_list, resp_time = query_by_time(self, query_dt)
        if warning_list:
            return Response(
                {
                    "code": 200,
                    "msg": "获取成功",
                    "data": {"warning": warning_list, "time": resp_time},
                }
            )

        # 2. 查不到时，在前后缓存窗口内返回最近一批结果（不触发重算）
        warning_list, resp_time, _ = query_nearest_by_time(self, query_dt)
        if warning_list:
            return Response(
                {
                    "code": 200,
                    "msg": "获取成功",
                    "data": {"warning": warning_list, "time": resp_time},
                }
            )

        return Response(
            {"code": 200, "msg": "未查询到预警数据", "data": {"warning": [], "time": ""}}
        )
