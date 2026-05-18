from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
import logging
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from django.db.models import Avg, Max, Min
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from lightning_warning.models import TAtmoData
from lightning_warning.celery_beat.schedule_component import compute_and_save, query_by_time


logger = logging.getLogger(__name__)


class Detail_Warning(APIView):
    @staticmethod
    def _beijing_tz() -> dt_timezone:
        return dt_timezone(timedelta(hours=8))  # 返回北京时区（UTC+8）

    def _format_api_time(self, end_dt) -> str:
        return end_dt.astimezone(self._beijing_tz()).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _stat_int_scaled(value, unit: str) -> int:
        if value is None:  # 如果值为None
            return 0  # 返回0
        v = float(value)  # 转换为浮点数
        if unit == "V/m":  # 如果单位是V/m
            v = v / 1000.0  # 转换为kV/m
        return int(round(v))  # 四舍五入后转为整数返回

    def _build_warning_list(self, start_dt, end_dt, field_key: str, unit: str) -> List[Dict[str, Any]]:
        time_key = "time"  # 时间字段键名
        device_rows = (
            TAtmoData.objects.filter(time__gte=start_dt, time__lte=end_dt)  # 查询时间范围内的数据
            .exclude(device_id__isnull=True)  # 排除device_id为空的数据
            .values("device_id")  # 按设备ID分组
            .annotate(max_val=Max("mesaure_value"), min_val=Min("mesaure_value"), avg_val=Avg("mesaure_value"))  # 计算最大值、最小值、平均值
            .order_by("device_id")  # 按设备ID排序
        )

        grouped_data: Dict[int, List[Dict[str, Any]]] = defaultdict(list)  # 创建设备数据分组字典
        raw_rows = (
            TAtmoData.objects.filter(time__gte=start_dt, time__lte=end_dt)  # 查询时间范围内的原始数据
            .exclude(device_id__isnull=True)  # 排除device_id为空的数据
            .values("device_id", "time", "mesaure_value", "avg_value", "rate", "warn")  # 获取指定字段
            .order_by("device_id", "time")  # 按设备ID和时间排序
        )
        for r in raw_rows:  # 遍历原始数据行
            grouped_data[int(r["device_id"])].append(r)  # 按设备ID分组存储

        warning_list: List[Dict[str, Any]] = []  # 创建预警列表
        for row in device_rows:  # 遍历每个设备的统计行
            device_pk = int(row["device_id"])  # 获取设备ID
            ser = grouped_data.get(device_pk, [])  # 获取该设备的原始数据序列
            pred = self.predict_lightning_by_electric_field(  # 调用雷电预测方法
                data=ser,  # 传入设备数据序列
                field_key=field_key,  # 电场字段名
                time_key=time_key,  # 时间字段名
                unit=unit,  # 单位
            )
            wtype = int(pred.get("warning_level", 0))  # 获取预警等级
            warning_list.append(  # 添加到预警列表
                {
                    "device_id": int(device_pk),  # 设备ID
                    "type": wtype,  # 预警类型
                    "max_val": self._stat_int_scaled(row["max_val"], unit),  # 缩放后的最大值
                    "min_val": self._stat_int_scaled(row["min_val"], unit),  # 缩放后的最小值
                    "avg_val": self._stat_int_scaled(row["avg_val"], unit),  # 缩放后的平均值
                }
            )
        return warning_list  # 返回预警列表

    def get(self, request):
        """获取雷电预警结果"""
        time_str = request.query_params.get("time")
        if not time_str:
            return Response({"code": 400, "msg": "缺少参数 time"})

        query_dt = parse_datetime(str(time_str))
        if query_dt is None:
            return Response(
                {
                    "code": 400,
                    "msg": "时间格式错误，请使用 ISO8601，例如 2026-05-10T12:06:00",
                    "data": [],
                }
            )

        if timezone.is_naive(query_dt):
            query_dt = query_dt.replace(tzinfo=self._beijing_tz())

        warning_list, resp_time = query_by_time(self, query_dt)
        if not warning_list:
            warning_list, resp_time = compute_and_save(self, query_dt)

        return Response(
            {
                "code": 200,
                "msg": "获取成功",
                "data": {"warning": warning_list, "time": resp_time},
            }
        )

    def predict_lightning_by_electric_field(
            self,
            data: List[Dict[str, Any]],
            field_key: str = "mesaure_value",
            time_key: str = "time",
            unit: str = "kV/m"
    ) -> Dict[str, Any]:

        if not data:  # 如果没有数据
            return self._empty_result("未传入电场数据。")  # 返回空结果

        if len(data) < 30:  # 如果数据量不足30条
            return self._empty_result("数据量不足，建议至少传入最近30秒以上数据。")  # 返回空结果

        fields = []  # 创建电场值列表
        times = []  # 创建时间列表

        for item in data:  # 遍历数据项
            try:
                value = float(item[field_key])  # 获取电场值并转为浮点数
                if unit == "V/m":  # 如果单位是V/m
                    value = value / 1000.0  # 转换为kV/m
                fields.append(value)  # 添加到电场值列表
                times.append(item.get(time_key))  # 添加时间到列表
            except Exception:  # 如果转换失败
                continue  # 跳过该项

        if len(fields) < 30:  # 如果有效数据不足30条
            return self._empty_result("有效电场数据不足，无法进行预警判断。")  # 返回空结果

        fields = np.array(fields, dtype=float)  # 转换为numpy数组
        fields = fields[-300:]  # 只保留最近300条数据
        times = times[-300:]  # 只保留最近300条时间

        features = self._calculate_electric_field_features(fields, times)  # 计算电场特征
        score_detail = self._calculate_warning_score(features)  # 计算预警分数
        score = score_detail["total_score"]  # 获取总分
        probability = round(score / 100.0, 2)  # 计算概率（分数/100）

        if score < 20:  # 如果分数小于20
            warning_level = 0  # 预警等级0
            warning_name = "正常"  # 预警名称
            message = "当前电场整体较平稳，雷电风险较低。"  # 提示信息
        elif score < 45:  # 如果分数在20-45之间
            warning_level = 1  # 预警等级1
            warning_name = "关注"  # 预警名称
            message = "电场出现一定增强或波动，建议持续关注。"  # 提示信息
        elif score < 75:  # 如果分数在45-75之间
            warning_level = 2  # 预警等级2
            warning_name = "警戒"  # 预警名称
            message = "电场强度或变化率明显升高，存在雷电活动风险。"  # 提示信息
        else:  # 如果分数大于等于75
            warning_level = 3  # 预警等级3
            warning_name = "高危"  # 预警名称
            message = "电场持续异常或剧烈变化，雷电风险较高，建议采取防雷措施。"  # 提示信息

        return {  # 返回预测结果
            "warning_level": warning_level,  # 预警等级
            "warning_name": warning_name,  # 预警名称
            "probability": probability,  # 概率
            "score": score,  # 分数
            "message": message,  # 提示信息
            "features": features,  # 特征数据
            "score_detail": score_detail,  # 分数详情
            "radius": {  # 预警半径信息
                "core_radius_km": 5,  # 核心预警半径（公里）
                "reference_radius_km": 10,  # 参考预警半径（公里）
                "max_reference_radius_km": 20,  # 最大参考半径（公里）
                "description": "单站电场仪建议以5km作为核心预警范围，10km作为参考预警范围，20km以内作为最大参考范围。"  # 描述
            }
        }

    def _calculate_electric_field_features(
            self,
            fields: np.ndarray,
            times: Optional[List[Any]] = None
    ) -> Dict[str, Any]:

        abs_fields = np.abs(fields)  # 计算电场绝对值
        recent_60 = fields[-60:] if len(fields) >= 60 else fields  # 获取最近60秒数据
        recent_60_abs = np.abs(recent_60)  # 计算最近60秒的绝对值
        recent_30_abs = abs_fields[-30:] if len(abs_fields) >= 30 else abs_fields  # 获取最近30秒的绝对值

        current_e = fields[-1]  # 获取当前电场值
        current_abs_e = abs(current_e)  # 获取当前电场绝对值

        mean_abs_5min = float(np.mean(abs_fields))  # 计算5分钟平均绝对电场
        max_abs_5min = float(np.max(abs_fields))  # 计算5分钟最大绝对电场
        std_abs_5min = float(np.std(abs_fields))  # 计算5分钟电场标准差

        mean_abs_60s = float(np.mean(recent_60_abs))  # 计算60秒平均绝对电场
        max_abs_60s = float(np.max(recent_60_abs))  # 计算60秒最大绝对电场
        std_abs_60s = float(np.std(recent_60_abs))  # 计算60秒电场标准差

        # 变化率
        diff_60 = np.diff(recent_60)  # 计算60秒数据的差分
        abs_diff_60 = np.abs(diff_60)  # 计算差分绝对值
        max_change_60s = float(np.max(abs_diff_60)) if abs_diff_60.size > 0 else 0.0  # 最大变化率
        mean_change_60s = float(np.mean(abs_diff_60)) if abs_diff_60.size > 0 else 0.0  # 平均变化率

        diff_5min = np.diff(fields)  # 计算5分钟数据的差分
        abs_diff_5min = np.abs(diff_5min)  # 计算差分绝对值
        max_change_5min = float(np.max(abs_diff_5min)) if abs_diff_5min.size > 0 else 0.0  # 5分钟最大变化率
        mean_change_5min = float(np.mean(abs_diff_5min)) if abs_diff_5min.size > 0 else 0.0  # 5分钟平均变化率

        # 极性反转
        sign_changes_60s = self._count_sign_changes(recent_60)  # 计算60秒内符号变化次数
        sign_changes_5min = self._count_sign_changes(fields)  # 计算5分钟内符号变化次数

        # 高电场持续时间
        high_field_duration_30s = int(np.sum(recent_30_abs >= 5.0))  # 计算30秒内电场>=5的持续时间
        high_field_duration_60s = int(np.sum(recent_60_abs >= 5.0))  # 计算60秒内电场>=5的持续时间

        # 趋势斜率
        trend_slope_60s = self._calculate_trend_slope(recent_60)  # 计算60秒趋势斜率
        trend_slope_5min = self._calculate_trend_slope(fields)  # 计算5分钟趋势斜率

        latest_time = times[-1] if times else None  # 获取最新时间

        return {  # 返回特征字典
            "latest_time": str(latest_time) if latest_time else None,  # 最新时间
            "data_count": int(len(fields)),  # 数据点数
            "current_e": round(float(current_e), 4),  # 当前电场值（保留4位小数）
            "current_abs_e": round(float(current_abs_e), 4),  # 当前电场绝对值
            "mean_abs_5min": round(mean_abs_5min, 4),  # 5分钟平均绝对电场
            "max_abs_5min": round(max_abs_5min, 4),  # 5分钟最大绝对电场
            "std_abs_5min": round(std_abs_5min, 4),  # 5分钟电场标准差
            "mean_abs_60s": round(mean_abs_60s, 4),  # 60秒平均绝对电场
            "max_abs_60s": round(max_abs_60s, 4),  # 60秒最大绝对电场
            "std_abs_60s": round(std_abs_60s, 4),  # 60秒电场标准差
            "max_change_5min": round(max_change_5min, 4),  # 5分钟最大变化率
            "mean_change_5min": round(mean_change_5min, 4),  # 5分钟平均变化率
            "max_change_60s": round(max_change_60s, 4),  # 60秒最大变化率
            "mean_change_60s": round(mean_change_60s, 4),  # 60秒平均变化率
            "sign_changes_5min": int(sign_changes_5min),  # 5分钟符号变化次数
            "sign_changes_60s": int(sign_changes_60s),  # 60秒符号变化次数
            "high_field_duration_30s": int(high_field_duration_30s),  # 30秒高电场持续时间
            "high_field_duration_60s": int(high_field_duration_60s),  # 60秒高电场持续时间
            "trend_slope_60s": round(float(trend_slope_60s), 4),  # 60秒趋势斜率
            "trend_slope_5min": round(float(trend_slope_5min), 4)  # 5分钟趋势斜率
        }

    def _calculate_warning_score(self, features: Dict[str, Any]) -> Dict[str, int]:
        score_detail = {}  # 创建分数详情字典
        mean_abs_60s = features["mean_abs_60s"]  # 获取60秒平均绝对电场
        max_abs_60s = features["max_abs_60s"]  # 获取60秒最大绝对电场
        mean_abs_5min = features["mean_abs_5min"]  # 获取5分钟平均绝对电场
        max_change_60s = features["max_change_60s"]  # 获取60秒最大变化率
        mean_change_60s = features["mean_change_60s"]  # 获取60秒平均变化率
        sign_changes_60s = features["sign_changes_60s"]  # 获取60秒符号变化次数
        high_field_duration_30s = features["high_field_duration_30s"]  # 获取30秒高电场持续时间
        high_field_duration_60s = features["high_field_duration_60s"]  # 获取60秒高电场持续时间
        trend_slope_60s = abs(features["trend_slope_60s"])  # 获取趋势斜率的绝对值

        # 1. 平均电场
        if mean_abs_60s >= 8:  # 如果60秒平均电场>=8
            mean_field_score = 35  # 得35分
        elif mean_abs_60s >= 5:  # 如果60秒平均电场>=5
            mean_field_score = 26  # 得26分
        elif mean_abs_60s >= 2:  # 如果60秒平均电场>=2
            mean_field_score = 12  # 得12分
        else:  # 否则
            mean_field_score = 0  # 得0分
        score_detail["mean_field_score"] = mean_field_score  # 保存分数

        # 2. 最大电场
        if max_abs_60s >= 10:  # 如果60秒最大电场>=10
            max_field_score = 20  # 得20分
        elif max_abs_60s >= 7:  # 如果60秒最大电场>=7
            max_field_score = 15  # 得15分
        elif max_abs_60s >= 4:  # 如果60秒最大电场>=4
            max_field_score = 8  # 得8分
        else:  # 否则
            max_field_score = 0  # 得0分
        score_detail["max_field_score"] = max_field_score  # 保存分数

        # 3. 5分钟平均
        if mean_abs_5min >= 5:  # 如果5分钟平均电场>=5
            mean_5min_score = 10  # 得10分
        elif mean_abs_5min >= 2:  # 如果5分钟平均电场>=2
            mean_5min_score = 5  # 得5分
        else:  # 否则
            mean_5min_score = 0  # 得0分
        score_detail["mean_5min_score"] = mean_5min_score  # 保存分数

        # 4. 最大变化率
        if max_change_60s >= 3:  # 如果60秒最大变化率>=3
            change_score = 20  # 得20分
        elif max_change_60s >= 1.5:  # 如果60秒最大变化率>=1.5
            change_score = 14  # 得14分
        elif max_change_60s >= 0.8:  # 如果60秒最大变化率>=0.8
            change_score = 7  # 得7分
        else:  # 否则
            change_score = 0  # 得0分
        score_detail["change_score"] = change_score  # 保存分数

        # 5. 平均变化率
        if mean_change_60s >= 1.0:  # 如果60秒平均变化率>=1.0
            mean_change_score = 5  # 得5分
        elif mean_change_60s >= 0.5:  # 如果60秒平均变化率>=0.5
            mean_change_score = 3  # 得3分
        else:  # 否则
            mean_change_score = 0  # 得0分
        score_detail["mean_change_score"] = mean_change_score  # 保存分数

        # 6. 极性反转
        if sign_changes_60s >= 3:  # 如果60秒符号变化>=3次
            sign_change_score = 5  # 得5分
        elif sign_changes_60s >= 1:  # 如果60秒符号变化>=1次
            sign_change_score = 3  # 得3分
        else:  # 否则
            sign_change_score = 0  # 得0分
        score_detail["sign_change_score"] = sign_change_score  # 保存分数

        # 7. 高电场持续时间
        if high_field_duration_60s >= 40:  # 如果60秒内高电场持续>=40秒
            duration_score = 10  # 得10分
        elif high_field_duration_30s >= 20:  # 如果30秒内高电场持续>=20秒
            duration_score = 8  # 得8分
        elif high_field_duration_30s >= 10:  # 如果30秒内高电场持续>=10秒
            duration_score = 5  # 得5分
        else:  # 否则
            duration_score = 0  # 得0分
        score_detail["duration_score"] = duration_score  # 保存分数

        # 8. 趋势斜率
        if trend_slope_60s >= 0.08:  # 如果趋势斜率>=0.08
            trend_score = 5  # 得5分
        elif trend_slope_60s >= 0.04:  # 如果趋势斜率>=0.04
            trend_score = 3  # 得3分
        else:  # 否则
            trend_score = 0  # 得0分
        score_detail["trend_score"] = trend_score  # 保存分数

        total_score = sum(score_detail.values())  # 计算总分
        score_detail["total_score"] = min(int(total_score), 100)  # 限制最高100分
        return score_detail  # 返回分数详情

    def _count_sign_changes(self, values: np.ndarray) -> int:
        signs = np.sign(values)  # 计算符号数组（正数为1，负数为-1，零为0）
        signs = signs[signs != 0]  # 过滤掉零值
        if len(signs) < 2:  # 如果符号数量少于2个
            return 0  # 返回0
        return int(np.sum(signs[1:] * signs[:-1] < 0))  # 计算相邻符号乘积为负的个数（即符号变化次数）

    def _calculate_trend_slope(self, values: np.ndarray) -> float:
        if len(values) < 2:  # 如果数据点少于2个
            return 0.0  # 返回0
        x = np.arange(len(values))  # 创建x轴数据（索引）
        y = values  # y轴数据（电场值）
        try:
            slope = np.polyfit(x, y, 1)[0]  # 使用一次多项式拟合计算斜率
            return float(slope)  # 返回斜率
        except Exception:  # 如果拟合失败
            return 0.0  # 返回0

    def _empty_result(self, message: str) -> Dict[str, Any]:
        return {  # 返回空结果字典
            "warning_level": 0,  # 预警等级0
            "warning_name": "数据不足",  # 预警名称
            "probability": 0.0,  # 概率0
            "score": 0,  # 分数0
            "message": message,  # 提示信息
            "features": None,  # 特征为空
            "score_detail": None,  # 分数详情为空
            "radius": {  # 预警半径信息
                "core_radius_km": 5,  # 核心预警半径
                "reference_radius_km": 10,  # 参考预警半径
                "max_reference_radius_km": 20  # 最大参考半径
            }
        }
