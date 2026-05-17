from django.urls import path

from apps.reflectance.view.views import ReflectanceView,WarningView
urlpatterns = [
    path('reflectance/', ReflectanceView.as_view()),
    path('warning/', WarningView.as_view())
]
