import logging

import cartopy.crs as ccrs
import cinrad
import matplotlib

matplotlib.use("Agg")  # 设置matplotlib后端为非交互式模式，适用于服务器环境
import matplotlib.pyplot as plt
import numpy as np
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from reflectance.celery_beat.precipitation_component import get_precipitation_from_local
from reflectance.celery_beat.schedule_component import (
    get_reflectance_exact_from_local,
    render_reflectance_image,
)
from reflectance.music.music_radar import radar_bin_path
from reflectance.music.precipitation import get_precipitation_product

logger = logging.getLogger(__name__)

# RADAR_BIN_PATH = Path(__file__).resolve().parent / "Z_RADA_C_BABJ_20260506000014_P_DOR_ACHN_CREF_20260505_235400.bin"

# 自定义异常类
class RadarDataError(APIException):
    status_code = 500  # HTTP状态码500
    default_detail = "雷达数据处理失败"  # 默认错误信息
    default_code = "radar_data_error"  # 错误代码

# 反射率图片生成接口
class ReflectanceView(APIView):
    def get(self, request):
        time_str = request.query_params.get("time")
        if not time_str:
            return Response({"code": 400, "msg": "缺少参数 time"})

        try:
            try:
                result = get_reflectance_exact_from_local(time_str)
            except NotFound:
                result = render_reflectance_image(time_str)
            return Response(
                {
                    "code": 200,
                    "msg": "获取成功",
                    "data": {
                        "url": result["image_url"],
                        "time": result["response_time"],
                    },
                }
            )
        except NotFound as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return Response({"code": 404, "msg": detail}, status=404)
        except Exception:
            logger.exception("反射率本地图片查询失败")
            raise RadarDataError(detail="数据处理失败，请稍后重试")


class PrecipitationView(APIView):
    product_key = ""

    def get(self, request):
        time_str = request.query_params.get("time")
        if not time_str:
            return Response({"code": 400, "msg": "缺少参数 time"})

        product = get_precipitation_product(self.product_key)

        try:
            result = get_precipitation_from_local(product.key, time_str)
            return Response(
                {
                    "code": 200,
                    "msg": "获取成功",
                    "data": {
                        "url": result["image_url"],
                        "time": result["response_time"],
                    },
                }
            )
        except NotFound as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return Response({"code": 404, "msg": detail}, status=404)
        except Exception:
            logger.exception("%s本地图片查询失败", product.label)
            raise RadarDataError(detail="数据处理失败，请稍后重试")


class PrecipitationOneHourView(PrecipitationView):
    product_key = "1h"


class PrecipitationThreeHourView(PrecipitationView):
    product_key = "3h"
