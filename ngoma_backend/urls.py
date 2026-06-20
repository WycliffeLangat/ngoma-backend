from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

admin.site.site_header = 'Ngoma Charts Admin'
admin.site.site_title = 'Ngoma Charts'
admin.site.index_title = "Kenya's Official Music Charts"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('charts.urls')),
    path('api-auth/', include('rest_framework.urls')),
    # Serve uploaded media files in all environments (dev and production)
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
