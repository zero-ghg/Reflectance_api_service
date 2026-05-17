from django.urls import path

from lightning_warning.view.views import Detail_Warning
urlpatterns = [
    path('lightning/', Detail_Warning.as_view()),
]
