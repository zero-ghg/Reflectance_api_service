from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('api/v1/', include('users.urls')),
    path('api/v1/radar/', include('reflectance.urls')),
    path('api/v1/warning/', include('lightning_warning.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
