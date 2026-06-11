from django.urls import path

from apps.nmc.views.nmc import (
    CmaImageProductHistoryView,
    CmaImageProductListView,
    SatelliteCloudImageView,
)

urlpatterns = [
    path("satellite-cloud/", SatelliteCloudImageView.as_view()),
    path("cma-products/", CmaImageProductListView.as_view()),
    path("cma-products/<str:product_key>/", CmaImageProductHistoryView.as_view()),
]
