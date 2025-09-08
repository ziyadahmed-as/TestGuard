# TestGuard/urls.py (main project)
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views


urlpatterns = [
    path('admin/', admin.site.urls),
    
        # Include core URLs
    path('', include('core.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    # Include exams URLs
    path('exams/', include('exams.urls', namespace='exams')),
]
urlpatterns += [
    path('accounts/', include('django.contrib.auth.urls')),
]
# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    