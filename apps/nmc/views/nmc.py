from rest_framework.views import APIView
from rest_framework.response import Response

from nmc.models import WeatherWarning
from nmc.serializers.nmc import WeatherWarningSerializer


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
        from nmc.tasks import sync_weather_warning_task

        task = sync_weather_warning_task.delay()

        return Response({
            "message": "天气预警同步任务已提交",
            "task_id": task.id,
        })