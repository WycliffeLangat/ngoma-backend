from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = 'Ngoma Charts Admin'
admin.site.site_title = 'Ngoma Charts'
admin.site.index_title = "Kenya's Official Music Charts"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('charts.urls')),
    path('api-auth/', include('rest_framework.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
