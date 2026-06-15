from django.urls import path

from apps.reflectance.view.views import (
    PrecipitationOneHourView,
    PrecipitationThreeHourView,
    ReflectanceView,
    ThunderstormNowcastView,
)

urlpatterns = [
    path("reflectance/", ReflectanceView.as_view()),
    path("thunderstorm/nowcast/", ThunderstormNowcastView.as_view()),
    path("precipitation/1h/", PrecipitationOneHourView.as_view()),
    path("precipitation/3h/", PrecipitationThreeHourView.as_view()),
]
