from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import token_refresh

urlpatterns = [
    path('api/v1/', include('users.urls')),
    path('api/v1/radar/', include('reflectance.urls')),
    path('api/v1/warning/', include('lightning_warning.urls')),
    path('api/v1/refresh/', token_refresh)
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
