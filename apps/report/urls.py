from django.urls import path

from report.view.views import Generate_report

urlpatterns = [
    path('gen/', Generate_report.as_view()),
]
