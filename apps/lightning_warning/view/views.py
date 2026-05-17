from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
import logging
from pathlib import Path
import sqlite3
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from django.conf import settings
from django.db.models import Avg, Max, Min
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from lightning_warning.models import TAtmoData
from lightning_warning.sqlite_store import save_lightning_warning_rows


# Create your views here.
logger = logging.getLogger(__name__)

SCHEDULE_LOOKBACK_MINUTES = 10
SCHEDULED_ENDPOINT = "lightning_schedule"


class Detail_Warning(APIView):
    @staticmethod
    def _beijing_tz() -> dt_timezone:
        return dt_timezone(timedelta(hours=8))

    def _make_tzaware_beijing(self, dt):
        if timezone.is_naive(dt):
            return dt.replace(tzinfo=self._beijing_tz())
        return dt

    def _parse_start_end(self, start_time: str, end_time: str) -> Tuple[Optional[Any], Optional[Any], Optional[str]]:
        end_dt = parse_datetime(end_time)
        start_dt = parse_datetime(start_time)
        if end_dt is None or start_dt is None:
            return None, None, "时间格式错误，请使用 ISO8601 格式"
        end_dt = self._make_tzaware_beijing(end_dt)
        start_dt = self._make_tzaware_beijing(start_dt)
        if start_dt > end_dt:
            return None, None, "开始时间不能晚于结束时间"
        return start_dt, end_dt, None

    def _format_api_time(self, end_dt) -> str:
        return end_dt.astimezone(self._beijing_tz()).strftime("%Y-%m-%d %H:%M:%S")

    def _parse_front_time(self, time_text: str) -> Tuple[Optional[Any], Optional[str]]:
        parsed = parse_datetime(str(time_text))
        if parsed is not None:
            return self._make_tzaware_beijing(parsed), None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S"):
            try:
                dt = datetime.strptime(str(time_text), fmt)
                return self._make_tzaware_beijing(dt), None
            except ValueError:
                continue
        return None, "time 参数格式错误，请使用 YYYY-MM-DD HH:MM[:SS] 或 ISO8601"

    @staticmethod
    def _stat_int_scaled(value, unit: str) -> int:
        if value is None:
            return 0
        v = float(value)
        if unit == "V/m":
            v = v / 1000.0
        return int(round(v))

    def _build_warning_list(self, start_dt, end_dt, field_key: str, unit: str) -> List[Dict[str, Any]]:
        time_key = "time"
        device_rows = (
            TAtmoData.objects.filter(time__gte=start_dt, time__lte=end_dt)
            .exclude(device_id__isnull=True)
            .values("device_id")
            .annotate(max_val=Max("mesaure_value"), min_val=Min("mesaure_value"), avg_val=Avg("mesaure_value"))
            .order_by("device_id")
        )

        grouped_data: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        raw_rows = (
            TAtmoData.objects.filter(time__gte=start_dt, time__lte=end_dt)
            .exclude(device_id__isnull=True)
            .values("device_id", "time", "mesaure_value", "avg_value", "rate", "warn")
            .order_by("device_id", "time")
        )
        for r in raw_rows:
            grouped_data[int(r["device_id"])].append(r)

        warning_list: List[Dict[str, Any]] = []
        for row in device_rows:
            device_pk = int(row["device_id"])
            ser = grouped_data.get(device_pk, [])
            pred = self.predict_lightning_by_electric_field(
                data=ser,
                field_key=field_key,
                time_key=time_key,
                unit=unit,
            )
            wtype = int(pred.get("warning_level", 0))
            warning_list.append(
                {
                    "device_id": int(device_pk),
                    "type": wtype,
                    "max_val": self._stat_int_scaled(row["max_val"], unit),
                    "min_val": self._stat_int_scaled(row["min_val"], unit),
                    "avg_val": self._stat_int_scaled(row["avg_val"], unit),
                }
            )
        return warning_list

    def _save_warning_rows(self, endpoint: str, start_time: str, end_time: str, response_time: str, rows) -> int:
        if not rows:
            return 0
        sqlite_path = Path(settings.BASE_DIR) / "db.sqlite3"
        return save_lightning_warning_rows(
            sqlite_db_path=sqlite_path,
            endpoint=endpoint,
            start_time=start_time,
            end_time=end_time,
            response_time=response_time,
            warning_rows=rows,
        )

    def run_scheduled_job(self):
        now_dt = timezone.now().astimezone(self._beijing_tz())
        end_dt = now_dt
        start_dt = end_dt - timedelta(minutes=SCHEDULE_LOOKBACK_MINUTES)
        warning_list = self._build_warning_list(start_dt, end_dt, field_key="mesaure_value", unit="kV/m")
        start_str = self._format_api_time(start_dt)
        end_str = self._format_api_time(end_dt)
        saved_count = self._save_warning_rows(
            endpoint=SCHEDULED_ENDPOINT,
            start_time=start_str,
            end_time=end_str,
            response_time=end_str,
            rows=warning_list,
        )
        msg = (
            f"lightning_warning 定时任务入库完成: response_time={end_str}, "
            f"rows={saved_count}, window=[{start_str},{end_str}]"
        )
        print(msg)
        logger.info(msg)

    def _compute_and_store_by_query_time(self, query_dt):
        end_dt = query_dt.astimezone(self._beijing_tz())
        start_dt = end_dt - timedelta(minutes=SCHEDULE_LOOKBACK_MINUTES)
        warning_list = self._build_warning_list(start_dt, end_dt, field_key="mesaure_value", unit="kV/m")
        start_str = self._format_api_time(start_dt)
        end_str = self._format_api_time(end_dt)
        self._save_warning_rows(
            endpoint=SCHEDULED_ENDPOINT,
            start_time=start_str,
            end_time=end_str,
            response_time=end_str,
            rows=warning_list,
        )
        return warning_list, end_str

    def _query_sqlite_by_time(self, query_dt):
        sqlite_path = Path(settings.BASE_DIR) / "db.sqlite3"
        if not sqlite_path.exists():
            return [], ""
        query_time = self._format_api_time(query_dt)
        with sqlite3.connect(str(sqlite_path)) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT response_time
                FROM lightning_warning_result
                WHERE response_time = ?
                LIMIT 1
                """,
                (query_time,),
            )
            row = cur.fetchone()
            if not row:
                return [], ""
            response_time = str(row[0])
            cur.execute(
                """
                SELECT device_id, warning_type, max_val, min_val, avg_val
                FROM lightning_warning_result
                WHERE response_time = ?
                ORDER BY device_id
                """,
                (response_time,),
            )
            rows = cur.fetchall()
        warning_list = [
            {
                "device_id": int(r[0]),
                "type": int(r[1]),
                "max_val": int(r[2]),
                "min_val": int(r[3]),
                "avg_val": int(r[4]),
            }
            for r in rows
        ]
        return warning_list, response_time

    def get(self, request):
        """
        按前端传入 time 从 SQLite 定时计算结果中查询最近一次预警。
        """
        query_time = request.query_params.get("time") or request.data.get("time")
        if not query_time:
            return Response({"code": 400, "msg": "缺少参数 time", "data": {}})

        query_dt, err = self._parse_front_time(str(query_time))
        if err:
            return Response({"code": 400, "msg": err, "data": {}})
        warning_list, time_str = self._query_sqlite_by_time(query_dt)
        if not warning_list:
            warning_list, time_str = self._compute_and_store_by_query_time(query_dt)

        return Response(
            {
                "code": 200,
                "msg": "获取成功",
                "data": {"warning": warning_list, "time": time_str},
            }
        )

    def predict_lightning_by_electric_field(
            self,
            data: List[Dict[str, Any]],
            field_key: str = "mesaure_value",
            time_key: str = "time",
            unit: str = "kV/m"
    ) -> Dict[str, Any]:

        if not data:
            return self._empty_result("未传入电场数据。")

        if len(data) < 30:
            return self._empty_result("数据量不足，建议至少传入最近30秒以上数据。")

        fields = []
        times = []

        for item in data:
            try:
                value = float(item[field_key])
                if unit == "V/m":
                    value = value / 1000.0
                fields.append(value)
                times.append(item.get(time_key))
            except Exception:
                continue

        if len(fields) < 30:
            return self._empty_result("有效电场数据不足，无法进行预警判断。")

        fields = np.array(fields, dtype=float)
        fields = fields[-300:]
        times = times[-300:]

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

    def _calculate_electric_field_features(
            self,
            fields: np.ndarray,
            times: Optional[List[Any]] = None
    ) -> Dict[str, Any]:

        abs_fields = np.abs(fields)
        recent_60 = fields[-60:] if len(fields) >= 60 else fields
        recent_60_abs = np.abs(recent_60)
        recent_30_abs = abs_fields[-30:] if len(abs_fields) >= 30 else abs_fields

        current_e = fields[-1]
        current_abs_e = abs(current_e)

        mean_abs_5min = float(np.mean(abs_fields))
        max_abs_5min = float(np.max(abs_fields))
        std_abs_5min = float(np.std(abs_fields))

        mean_abs_60s = float(np.mean(recent_60_abs))
        max_abs_60s = float(np.max(recent_60_abs))
        std_abs_60s = float(np.std(recent_60_abs))

        # 变化率
        diff_60 = np.diff(recent_60)
        abs_diff_60 = np.abs(diff_60)
        max_change_60s = float(np.max(abs_diff_60)) if abs_diff_60.size > 0 else 0.0
        mean_change_60s = float(np.mean(abs_diff_60)) if abs_diff_60.size > 0 else 0.0

        diff_5min = np.diff(fields)
        abs_diff_5min = np.abs(diff_5min)
        max_change_5min = float(np.max(abs_diff_5min)) if abs_diff_5min.size > 0 else 0.0
        mean_change_5min = float(np.mean(abs_diff_5min)) if abs_diff_5min.size > 0 else 0.0

        # 极性反转
        sign_changes_60s = self._count_sign_changes(recent_60)
        sign_changes_5min = self._count_sign_changes(fields)

        # 高电场持续时间
        high_field_duration_30s = int(np.sum(recent_30_abs >= 5.0))
        high_field_duration_60s = int(np.sum(recent_60_abs >= 5.0))

        # 趋势斜率
        trend_slope_60s = self._calculate_trend_slope(recent_60)
        trend_slope_5min = self._calculate_trend_slope(fields)

        latest_time = times[-1] if times else None

        return {
            "latest_time": str(latest_time) if latest_time else None,
            "data_count": int(len(fields)),
            "current_e": round(float(current_e), 4),
            "current_abs_e": round(float(current_abs_e), 4),
            "mean_abs_5min": round(mean_abs_5min, 4),
            "max_abs_5min": round(max_abs_5min, 4),
            "std_abs_5min": round(std_abs_5min, 4),
            "mean_abs_60s": round(mean_abs_60s, 4),
            "max_abs_60s": round(max_abs_60s, 4),
            "std_abs_60s": round(std_abs_60s, 4),
            "max_change_5min": round(max_change_5min, 4),
            "mean_change_5min": round(mean_change_5min, 4),
            "max_change_60s": round(max_change_60s, 4),
            "mean_change_60s": round(mean_change_60s, 4),
            "sign_changes_5min": int(sign_changes_5min),
            "sign_changes_60s": int(sign_changes_60s),
            "high_field_duration_30s": int(high_field_duration_30s),
            "high_field_duration_60s": int(high_field_duration_60s),
            "trend_slope_60s": round(float(trend_slope_60s), 4),
            "trend_slope_5min": round(float(trend_slope_5min), 4)
        }

    def _calculate_warning_score(self, features: Dict[str, Any]) -> Dict[str, int]:
        score_detail = {}
        mean_abs_60s = features["mean_abs_60s"]
        max_abs_60s = features["max_abs_60s"]
        mean_abs_5min = features["mean_abs_5min"]
        max_change_60s = features["max_change_60s"]
        mean_change_60s = features["mean_change_60s"]
        sign_changes_60s = features["sign_changes_60s"]
        high_field_duration_30s = features["high_field_duration_30s"]
        high_field_duration_60s = features["high_field_duration_60s"]
        trend_slope_60s = abs(features["trend_slope_60s"])

        # 1. 平均电场
        if mean_abs_60s >= 8:
            mean_field_score = 35
        elif mean_abs_60s >= 5:
            mean_field_score = 26
        elif mean_abs_60s >= 2:
            mean_field_score = 12
        else:
            mean_field_score = 0
        score_detail["mean_field_score"] = mean_field_score

        # 2. 最大电场
        if max_abs_60s >= 10:
            max_field_score = 20
        elif max_abs_60s >= 7:
            max_field_score = 15
        elif max_abs_60s >= 4:
            max_field_score = 8
        else:
            max_field_score = 0
        score_detail["max_field_score"] = max_field_score

        # 3. 5分钟平均
        if mean_abs_5min >= 5:
            mean_5min_score = 10
        elif mean_abs_5min >= 2:
            mean_5min_score = 5
        else:
            mean_5min_score = 0
        score_detail["mean_5min_score"] = mean_5min_score

        # 4. 最大变化率
        if max_change_60s >= 3:
            change_score = 20
        elif max_change_60s >= 1.5:
            change_score = 14
        elif max_change_60s >= 0.8:
            change_score = 7
        else:
            change_score = 0
        score_detail["change_score"] = change_score

        # 5. 平均变化率
        if mean_change_60s >= 1.0:
            mean_change_score = 5
        elif mean_change_60s >= 0.5:
            mean_change_score = 3
        else:
            mean_change_score = 0
        score_detail["mean_change_score"] = mean_change_score

        # 6. 极性反转
        if sign_changes_60s >= 3:
            sign_change_score = 5
        elif sign_changes_60s >= 1:
            sign_change_score = 3
        else:
            sign_change_score = 0
        score_detail["sign_change_score"] = sign_change_score

        # 7. 高电场持续时间
        if high_field_duration_60s >= 40:
            duration_score = 10
        elif high_field_duration_30s >= 20:
            duration_score = 8
        elif high_field_duration_30s >= 10:
            duration_score = 5
        else:
            duration_score = 0
        score_detail["duration_score"] = duration_score

        # 8. 趋势斜率
        if trend_slope_60s >= 0.08:
            trend_score = 5
        elif trend_slope_60s >= 0.04:
            trend_score = 3
        else:
            trend_score = 0
        score_detail["trend_score"] = trend_score

        total_score = sum(score_detail.values())
        score_detail["total_score"] = min(int(total_score), 100)
        return score_detail

    def _count_sign_changes(self, values: np.ndarray) -> int:
        signs = np.sign(values)
        signs = signs[signs != 0]
        if len(signs) < 2:
            return 0
        return int(np.sum(signs[1:] * signs[:-1] < 0))

    def _calculate_trend_slope(self, values: np.ndarray) -> float:
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


def run_lightning_warning_schedule_once():
    """供调度组件调用：执行一次雷电预警定时计算。"""
    try:
        Detail_Warning().run_scheduled_job()
    except Exception:
        logger.exception("雷电预警定时任务执行失败")
