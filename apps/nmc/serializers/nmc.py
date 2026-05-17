from rest_framework import serializers

from nmc.models import WeatherWarning


class WeatherWarningSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeatherWarning
        fields = [
            "id",
            "warning_id",
            "publish_id",
            "pid",
            "warn_code",
            "warn_time",
            "warn_period",
            "warn_type",
            "warn_level",
            "signal_type",
            "is_active",
            "warn_content",
            "warn_area",
            "warn_measure",
            "area_code",
            "publish_unit",
            "status",
            "make_time",
            "created_at",
            "updated_at",
        ]