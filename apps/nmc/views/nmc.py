from rest_framework.views import APIView
from rest_framework.response import Response

from apps.nmc.cma_image_products import (
    find_local_cma_image_product,
    get_cma_image_product,
    list_cma_image_product_configs,
    list_local_cma_image_products,
)
from apps.nmc.models import WeatherWarning
from apps.nmc.serializers.nmc import WeatherWarningSerializer
from apps.nmc.satellite_cloud import list_local_satellite_cloud_images


class ActiveWeatherWarningView(APIView):
    """
    查询正在预警的内容。
    不返回已解除预警。
    """

    def get(self, request):
        area_code = request.query_params.get("area_code")
        warn_type = request.query_params.get("warn_type")
        warn_level = request.query_params.get("warn_level")

        queryset = WeatherWarning.objects.filter(
            is_active=True,
            status="3",
        ).order_by("-warn_time")

        if area_code:
            queryset = queryset.filter(area_code=area_code)

        if warn_type:
            queryset = queryset.filter(warn_type=warn_type)

        if warn_level:
            queryset = queryset.filter(warn_level=warn_level)

        serializer = WeatherWarningSerializer(queryset, many=True)

        return Response({
            "count": queryset.count(),
            "data": serializer.data,
        })


class SyncWeatherWarningView(APIView):
    """
    手动触发一次同步，方便测试。
    """

    def post(self, request):
        from apps.nmc.tasks import sync_weather_warning_task

        task = sync_weather_warning_task.delay()

        return Response({
            "message": "天气预警同步任务已提交",
            "task_id": task.id,
        })


class SatelliteCloudImageView(APIView):
    """
    查询本地 FY4B 卫星云图。
    """

    def get(self, request):
        limit_text = request.query_params.get("limit", "100")
        try:
            limit = int(limit_text)
        except (TypeError, ValueError):
            return Response({"code": 400, "msg": "limit 必须是整数"}, status=400)

        images = list_local_satellite_cloud_images(limit=limit)
        latest = images[0] if images else None

        return Response(
            {
                "code": 200,
                "msg": "获取成功",
                "data": {
                    "latest": latest,
                    "items": images,
                },
            }
        )


class CmaImageProductListView(APIView):
    """
    查询支持的 CMA 图片产品。
    """

    def get(self, request):
        return Response(
            {
                "code": 200,
                "msg": "获取成功",
                "data": {
                    "items": list_cma_image_product_configs(),
                },
            }
        )


class CmaImageProductHistoryView(APIView):
    """
    查询 CMA 图片产品本地历史。
    """

    def get(self, request, product_key):
        try:
            product = get_cma_image_product(product_key)
        except ValueError as exc:
            return Response({"code": 404, "msg": str(exc)}, status=404)

        limit_text = request.query_params.get("limit", "100")
        try:
            limit = int(limit_text)
        except (TypeError, ValueError):
            return Response({"code": 400, "msg": "limit 必须是整数"}, status=400)

        time_text = request.query_params.get("time")
        selected = None
        if time_text:
            try:
                selected = find_local_cma_image_product(product.key, time_text)
            except ValueError as exc:
                return Response({"code": 400, "msg": str(exc)}, status=400)
            if selected is None:
                return Response({"code": 404, "msg": "本地暂无指定时次图片"}, status=404)

        images = list_local_cma_image_products(product.key, limit=limit)
        latest = images[0] if images else None
        current = selected or latest

        return Response(
            {
                "code": 200,
                "msg": "获取成功",
                "data": {
                    "product": product.key,
                    "product_name": product.label,
                    "description": product.description,
                    "latest": latest,
                    "current": current,
                    "times": [item.get("time") for item in images if item.get("time")],
                    "items": images,
                },
            }
        )
