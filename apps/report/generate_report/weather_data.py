#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天气数据采集组件。
"""
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple

import requests


class WeatherDataComponent:
    """负责天气数据采集、风险分析和 JSON 落盘。"""

    def __init__(self, api_id: str = "10016765", api_key: str = "99ed9f07ef96ba4a838ed25a0e540e56"):
        self.base_url = "https://cn.apihz.cn/api/tianqi/tqyb.php"
        self.api_id = api_id
        self.api_key = api_key
        self.tianjin_districts = [
            {"province": "天津", "city": "天津", "name": "天津市区"},
            {"province": "天津", "city": "滨海新区", "name": "滨海新区"},
            {"province": "天津", "city": "武清", "name": "武清区"},
            {"province": "天津", "city": "宝坻", "name": "宝坻区"},
            {"province": "天津", "city": "宁河", "name": "宁河区"},
            {"province": "天津", "city": "静海", "name": "静海区"},
            {"province": "天津", "city": "蓟州", "name": "蓟州区"},
            {"province": "天津", "city": "西青", "name": "西青区"},
            {"province": "天津", "city": "津南", "name": "津南区"},
            {"province": "天津", "city": "北辰", "name": "北辰区"},
            {"province": "天津", "city": "东丽", "name": "东丽区"},
        ]

    def get_weather(self, province: str, city: str, days: int = 1, hourly: bool = False) -> Dict[str, Any]:
        params = {
            "id": self.api_id,
            "key": self.api_key,
            "sheng": province,
            "place": city,
            "day": days,
            "hourtype": 1 if hourly else 0,
        }
        response = requests.get(self.base_url, params=params, timeout=10)
        response.raise_for_status()
        weather_data = response.json()
        if weather_data.get("code") != 200:
            raise ValueError(f"API请求失败: {weather_data.get('msg', '未知错误')}")
        return weather_data

    def get_all_districts_weather(self, days: int = 3, hourly: bool = True) -> List[Dict[str, Any]]:
        all_weather_data: List[Dict[str, Any]] = []
        print(f"正在获取天津{len(self.tianjin_districts)}个区域的天气数据...")
        print("=" * 60)
        for idx, district in enumerate(self.tianjin_districts, start=1):
            try:
                print(f"[{idx}/{len(self.tianjin_districts)}] 获取 {district['name']} ...")
                weather_data = self.get_weather(district["province"], district["city"], days=days, hourly=hourly)
                weather_data["district_name"] = district["name"]
                all_weather_data.append(weather_data)
                print(f"  ✓ {district['name']} 成功")
            except Exception as exc:
                print(f"  ✗ {district['name']} 失败: {exc}")
        print("=" * 60)
        print(f"✅ 成功获取 {len(all_weather_data)}/{len(self.tianjin_districts)} 个区域\n")
        return all_weather_data

    @staticmethod
    def _to_number(value: Any, default: float = 0) -> float:
        try:
            return float(str(value).replace("℃", "").strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optimize_nowinfo(nowinfo: Dict[str, Any]) -> Dict[str, Any]:
        if not nowinfo:
            return {}
        keep_keys = (
            "temperature",
            "pressure",
            "humidity",
            "windDirection",
            "windSpeed",
            "windScale",
            "uptime",
        )
        return {k: nowinfo.get(k) for k in keep_keys if k in nowinfo}

    @staticmethod
    def _optimize_day(day_data: Dict[str, Any], include_date: bool = False) -> Dict[str, Any]:
        if not day_data:
            return {}
        keep_keys = [
            "weather1",
            "weather2",
            "wd1",
            "wd2",
            "winddirection1",
            "winddirection2",
            "windleve1",
            "windleve2",
        ]
        if include_date:
            keep_keys.insert(0, "date")
        return {k: day_data.get(k) for k in keep_keys if k in day_data}

    @staticmethod
    def _optimize_hour(hour_item: Dict[str, Any]) -> Dict[str, Any]:
        keep_keys = ("时间", "天气", "气温", "降水", "风速", "风向", "气压", "湿度")
        return {k: hour_item.get(k) for k in keep_keys if k in hour_item}

    def optimize_weather_data(self, all_weather_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """精简接口原始数据，移除图标 URL 与无关字段。"""
        optimized: List[Dict[str, Any]] = []
        for item in all_weather_data:
            cleaned: Dict[str, Any] = {
                "district_name": item.get("district_name"),
                "uptime": item.get("uptime"),
                "nowdate": item.get("nowdate"),
                "weather1": item.get("weather1"),
                "weather2": item.get("weather2"),
                "wd1": item.get("wd1"),
                "wd2": item.get("wd2"),
                "winddirection1": item.get("winddirection1"),
                "winddirection2": item.get("winddirection2"),
                "windleve1": item.get("windleve1"),
                "windleve2": item.get("windleve2"),
                "nowinfo": self._optimize_nowinfo(item.get("nowinfo", {})),
                "weatherday2": self._optimize_day(item.get("weatherday2", {}), include_date=True),
                "weatherday3": self._optimize_day(item.get("weatherday3", {}), include_date=True),
                "alarm": item.get("alarm", []),
                "hourtime": item.get("hourtime"),
                "hour1": [self._optimize_hour(h) for h in item.get("hour1", [])],
                "hour2": [self._optimize_hour(h) for h in item.get("hour2", [])],
                "hour3": [self._optimize_hour(h) for h in item.get("hour3", [])],
            }
            optimized.append(cleaned)
        return optimized

    def analyze_weather_risks(self, all_weather_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        risk_summary = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_districts": len(all_weather_data),
            "districts_with_warnings": [],
            "overall_risk_level": "低",
            "key_risks": [],
        }

        high_rain_keywords = ["暴雨", "大暴雨", "特大暴雨", "中雨"]
        for data in all_weather_data:
            district_name = data.get("district_name", "未知")
            warnings: List[str] = []

            nowinfo = data.get("nowinfo", {})
            if nowinfo:
                temp = self._to_number(nowinfo.get("temperature", 0))
                humidity = self._to_number(nowinfo.get("humidity", 0))
                wind_speed = self._to_number(nowinfo.get("windSpeed", 0))
                if temp > 35:
                    warnings.append(f"高温预警: 当前温度{temp}℃")
                elif temp < -10:
                    warnings.append(f"低温预警: 当前温度{temp}℃")
                if humidity > 90:
                    warnings.append(f"高湿度: {humidity}%")
                if wind_speed > 17:
                    warnings.append(f"大风预警: 风速{wind_speed}m/s")

            for day_idx in range(1, 4):
                day_data = data if day_idx == 1 else data.get(f"weatherday{day_idx}", {})
                if not day_data:
                    continue

                weather_day = day_data.get("weather1", "")
                weather_night = day_data.get("weather2", "")
                temp_high = self._to_number(day_data.get("wd1", 0))
                temp_low = self._to_number(day_data.get("wd2", 0))

                for keyword in high_rain_keywords:
                    if keyword in weather_day or keyword in weather_night:
                        warnings.append(f"第{day_idx}天降雨预警: {weather_day}转{weather_night}")
                        break

                if temp_high > 35:
                    warnings.append(f"第{day_idx}天高温: 最高{temp_high}℃")
                elif temp_low < -10:
                    warnings.append(f"第{day_idx}天低温: 最低{temp_low}℃")

                wind_level = day_data.get("windleve1", "")
                if "7级" in wind_level or "8级" in wind_level or "9级" in wind_level:
                    warnings.append(f"第{day_idx}天大风: {wind_level}")

            for hour_idx in range(1, 4):
                for hour in data.get(f"hour{hour_idx}", []):
                    rain = hour.get("降水", "")
                    if "mm" not in rain:
                        continue
                    try:
                        rain_value = float(rain.replace("mm", ""))
                    except (TypeError, ValueError):
                        continue
                    if rain_value > 5:
                        time_str = hour.get("时间", "")
                        warnings.append(f"第{hour_idx}天{time_str}强降水: {rain}")

            if warnings:
                risk_summary["districts_with_warnings"].append(
                    {"district": district_name, "warnings": warnings, "risk_count": len(warnings)}
                )

        total_warnings = sum(d["risk_count"] for d in risk_summary["districts_with_warnings"])
        if total_warnings > 20:
            risk_summary["overall_risk_level"] = "高"
        elif total_warnings > 10:
            risk_summary["overall_risk_level"] = "中"
        return risk_summary

    def save_weather_data(
        self,
        all_weather_data: List[Dict[str, Any]],
        risk_summary: Dict[str, Any],
        weather_path: str = "tianjin_weather_data.json",
        risk_path: str = "tianjin_risk_analysis.json",
    ) -> Tuple[str, str]:
        optimized_data = self.optimize_weather_data(all_weather_data)
        with open(weather_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "districts_count": len(optimized_data),
                    "data": optimized_data,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        with open(risk_path, "w", encoding="utf-8") as f:
            json.dump(risk_summary, f, ensure_ascii=False, indent=2)
        print("📁 数据已保存:")
        print(f"  - {weather_path}")
        print(f"  - {risk_path}")
        return weather_path, risk_path

    def run(self, days: int = 3, hourly: bool = True) -> Tuple[str, str, Dict[str, Any]]:
        all_weather_data = self.get_all_districts_weather(days=days, hourly=hourly)
        if not all_weather_data:
            raise RuntimeError("未能获取任何天气数据")
        risk_summary = self.analyze_weather_risks(all_weather_data)
        weather_path, risk_path = self.save_weather_data(all_weather_data, risk_summary)
        return weather_path, risk_path, risk_summary
