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
from reflectance.celery_beat.schedule_component import get_reflectance_from_local
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
            result = get_reflectance_from_local(time_str)
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

#天津预警数据接口
class WarningView(APIView):

    MIN_MM = 30.0
    TIANJIN_LON_MIN = 116.7  # 最小经度
    TIANJIN_LON_MAX = 118.3  # 最大经度
    TIANJIN_LAT_MIN = 38.5  # 最小纬度
    TIANJIN_LAT_MAX = 40.5  # 最大纬度

    @staticmethod  # 静态方法，提取天津区域dBZ数据点
    def _tianjin_dbz_points(lon, lat, data):
        lon = np.asarray(lon)  # 转换为numpy数组
        lat = np.asarray(lat)
        data = np.asarray(data)

        # 处理掩码数组
        if hasattr(data, "mask"):  # 如果是MaskedArray
            valid = ~np.asarray(data.mask)  # 有效数据掩码（True表示有效）
            arr = np.ma.filled(data, np.nan)  # 掩码值填充为NaN
        else:  # 普通数组
            arr = data.astype(float, copy=False)  # 转为float类型
            valid = ~np.isnan(arr)  # 非NaN的为有效数据

        # 处理2D经纬度网格的情况
        if lon.ndim == 2 and lat.ndim == 2:  # 如果是2D网格
            in_tianjin = (  # 判断是否在天津范围内
                (lon >= WarningView.TIANJIN_LON_MIN)
                & (lon <= WarningView.TIANJIN_LON_MAX)
                & (lat >= WarningView.TIANJIN_LAT_MIN)
                & (lat <= WarningView.TIANJIN_LAT_MAX)
            )
            dbz_condition = in_tianjin & (arr >= WarningView.MIN_MM) & valid  # 筛选条件：在天津范围内且dBZ>=15且有效
            rr, cc = np.where(dbz_condition)  # 获取满足条件的行列索引
            dbz_lats = lat[rr, cc]  # 提取纬度
            dbz_lons = lon[rr, cc]  # 提取经度
            dbz_values = arr[rr, cc]  # 提取dBZ值
        else:  # 1D经纬度数组的情况
            lon_indices = np.where((lon >= WarningView.TIANJIN_LON_MIN) & (lon <= WarningView.TIANJIN_LON_MAX))[0]  # 经度索引
            lat_indices = np.where((lat >= WarningView.TIANJIN_LAT_MIN) & (lat <= WarningView.TIANJIN_LAT_MAX))[0]  # 纬度索引
            if len(lon_indices) == 0 or len(lat_indices) == 0:  # 如果没有索引
                return []  # 返回空列表
            tianjin_data = data[np.ix_(lat_indices, lon_indices)]  # 提取天津区域数据
            tianjin_lons = lon[lon_indices]  # 天津区域经度
            tianjin_lats = lat[lat_indices]  # 天津区域纬度

            # 再次处理掩码
            if hasattr(tianjin_data, "mask"):
                tj_valid = ~np.asarray(tianjin_data.mask)
                td = np.ma.filled(tianjin_data, np.nan)
            else:
                td = np.asarray(tianjin_data, dtype=float)
                tj_valid = ~np.isnan(td)

            dbz_condition = (td >= WarningView.MIN_MM) & tj_valid  # 筛选条件：dBZ>=15且有效
            dbz_indices = np.where(dbz_condition)  # 获取索引
            if len(dbz_indices[0]) == 0:  # 如果没有数据
                return []
            dbz_row_indices = dbz_indices[0]  # 行索引
            dbz_col_indices = dbz_indices[1]  # 列索引
            dbz_lats = tianjin_lats[dbz_row_indices]  # 纬度
            dbz_lons = tianjin_lons[dbz_col_indices]  # 经度
            dbz_values = td[dbz_condition]  # dBZ值

        sorted_order = np.argsort(dbz_values)[::-1]  # 按dBZ值降序排序的索引
        result_data = []  # 结果列表
        for rank, idx in enumerate(sorted_order):  # 遍历排序后的索引
            result_data.append(  # 添加到结果列表
                {
                    "lon": float(dbz_lons[idx]),  # 经度
                    "lat": float(dbz_lats[idx]),  # 纬度
                    "dbz": float(dbz_values[idx]),  # dBZ值
                }
            )
        return result_data  # 返回结果列表

    def get(self, request):
        try:
            with radar_bin_path(request) as (file_path, _selected_time):
                f = cinrad.io.MocMosaic(str(file_path))  # 读取雷达数据
                result_data = self._tianjin_dbz_points(f.lon, f.lat, f.data)  # 调用方法提取数据

        except NotFound:
            raise
        except OSError as exc:
            logger.exception("MUSIC 获取雷达文件失败")
            raise RadarDataError(detail=str(exc)) from exc
        except RadarDataError:
            raise
        except Exception:
            logger.exception("天津预警数据处理失败")
            raise RadarDataError(detail="数据处理失败，请稍后重试")

        # print(len(result_data))

        return Response(
            {
                "code": 200,
                "msg": "获取成功",
                "total_points": len(result_data),
                "data": result_data,
            }
        )
