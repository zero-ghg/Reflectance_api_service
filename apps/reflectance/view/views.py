import logging
import json
from pathlib import Path
import cartopy.crs as ccrs
import cinrad
import matplotlib

matplotlib.use("Agg")  # 设置matplotlib后端为非交互式模式，适用于服务器环境
import matplotlib.pyplot as plt
import numpy as np
from django.conf import settings
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from reflectance.music.music_radar import radar_bin_path

logger = logging.getLogger(__name__)
REFLECTANCE_RENDER_DPI = 600

# RADAR_BIN_PATH = Path(__file__).resolve().parent / "Z_RADA_C_BABJ_20260506000014_P_DOR_ACHN_CREF_20260505_235400.bin"

# 自定义异常类
class RadarDataError(APIException):
    status_code = 500  # HTTP状态码500
    default_detail = "雷达数据处理失败"  # 默认错误信息
    default_code = "radar_data_error"  # 错误代码

# 辅助函数，处理数据用于绘图
def _data_for_plot(data):
    d = np.ma.masked_invalid(np.asarray(data, dtype=float))  # 将无效数据掩码
    return np.where(d.mask, np.nan, d.filled(np.nan))  # 掩码数据替换为NaN

# 反射率图片生成接口
class ReflectanceView(APIView):
    def get(self, request):
        time_str = request.query_params.get("time")
        if not time_str:
            return Response({"code": 400, "msg": "缺少参数 time"})

        try:
            with radar_bin_path(request) as (file_path, selected_time):
                img_dir = Path(settings.MEDIA_ROOT) / "reflectance"
                img_dir.mkdir(parents=True, exist_ok=True)

                # 高优先级性能优化：按已选 bin 时次缓存渲染结果，命中则直接返回
                cache_key = (
                    selected_time.replace("-", "").replace(":", "").replace(" ", "")
                    if selected_time
                    else Path(file_path).stem
                )
                image_filename = f"reflectance_{cache_key}.png"
                image_path = img_dir / image_filename
                meta_path = image_path.with_suffix(".json")
                corners = None
                response_time = selected_time

                if image_path.exists():
                    # 命中图片缓存时，优先读取同名元数据缓存，避免再次解析 bin
                    if meta_path.exists():
                        try:
                            meta = json.loads(meta_path.read_text(encoding="utf-8"))
                            corners = meta.get("corners")
                            response_time = meta.get("time", response_time) or response_time
                        except (OSError, json.JSONDecodeError):
                            corners = None

                    # 兼容历史缓存：没有元数据时，回退到读取 bin 计算 corners 并补写元数据
                    if not corners:
                        f = cinrad.io.MocMosaic(str(file_path))
                        min_lon = float(np.nanmin(f.lon))
                        max_lon = float(np.nanmax(f.lon))
                        min_lat = float(np.nanmin(f.lat))
                        max_lat = float(np.nanmax(f.lat))
                        corners = {
                            "left_bottom": {"lon": min_lon, "lat": min_lat},
                            "right_bottom": {"lon": max_lon, "lat": min_lat},
                            "right_top": {"lon": max_lon, "lat": max_lat},
                            "left_top": {"lon": min_lon, "lat": max_lat},
                        }
                        try:
                            meta_path.write_text(
                                json.dumps({"time": response_time, "corners": corners}, ensure_ascii=False),
                                encoding="utf-8",
                            )
                        except OSError:
                            pass

                else:
                    f = cinrad.io.MocMosaic(str(file_path))  # 读取雷达bin文件
                    data_transparent = _data_for_plot(f.data)  # 处理数据用于绘图

                    # 与降水图一致：无回波/占位格点常为 0，jet+vmin=0 会整块深蓝；<1 视为透明
                    arr = np.asarray(data_transparent, dtype=float)
                    data_plot = np.where(np.isfinite(arr) & (arr < 1), np.nan, arr)

                    fig, ax = plt.subplots(
                        figsize=(16, 12),
                        subplot_kw={"projection": ccrs.PlateCarree()},
                        facecolor="none",
                    )

                    # 强制设置坐标轴和图形背景为透明
                    ax.set_facecolor("none")
                    fig.patch.set_facecolor("none")
                    ax.patch.set_facecolor("none")
                    ax.patch.set_alpha(0.0)
                    ax.patch.set_visible(False)

                    # 关键：关闭 Cartopy 默认的 Ocean 底图
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
                        vmin=0, vmax=70,
                        shading="auto",
                        transform=ccrs.PlateCarree(),
                        alpha=1.0,
                    )

                    min_lon = float(np.nanmin(f.lon))
                    max_lon = float(np.nanmax(f.lon))
                    min_lat = float(np.nanmin(f.lat))
                    max_lat = float(np.nanmax(f.lat))
                    corners = {
                        "left_bottom": {"lon": min_lon, "lat": min_lat},
                        "right_bottom": {"lon": max_lon, "lat": min_lat},
                        "right_top": {"lon": max_lon, "lat": max_lat},
                        "left_top": {"lon": min_lon, "lat": max_lat},
                    }

                    ax.set_extent(
                        [min_lon, max_lon, min_lat, max_lat],
                        crs=ccrs.PlateCarree(),
                    )
                    # 再次确保背景不可见（防止 set_extent 后重新触发）
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

            media_url = settings.MEDIA_URL  # 获取媒体URL
            if not str(media_url).endswith("/"):  # 确保URL以/结尾
                media_url = f"{media_url}/"
            image_url = f"{media_url}reflectance/{image_filename}" # 完整图片URL
            return Response(
                {
                    "code": 200,
                    "msg": "获取成功",
                    "data": {
                        "url": image_url,
                        "time": response_time,
                        # "corners": corners or {},
                    },
                }
            )

        except NotFound:  # 捕获文件不存在异常
            raise
        except OSError as exc:
            logger.exception("MUSIC 获取雷达文件失败")
            raise RadarDataError(detail=str(exc)) from exc
        except RadarDataError:  # 捕获雷达数据异常
            raise
        except Exception:  # 捕获其他所有异常
            logger.exception("雷达反射率出图失败")  # 记录异常日志
            raise RadarDataError(detail="数据处理失败，请稍后重试")  # 抛出统一异常

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
