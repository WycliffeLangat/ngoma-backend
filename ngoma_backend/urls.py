import os
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
from django.views.generic import RedirectView

admin.site.site_header = 'Ngoma Charts Admin'
admin.site.site_title = 'Ngoma Charts'
admin.site.index_title = "Kenya's Official Music Charts"

CMS_FRONTEND_URL = os.environ.get(
    'CMS_FRONTEND_URL',
    'https://candid-taffy-ccdbd5.netlify.app/cms/',
)

urlpatterns = [
    # The editorial CMS is the primary admin experience. Django admin remains
    # available as a technical fallback and for direct legacy model links.
    path('admin/', RedirectView.as_view(
        url=CMS_FRONTEND_URL,
        permanent=False,
        query_string=True,
    ), name='admin-workspace'),
    path('django-admin/', admin.site.urls),
    path('api/v1/', include('charts.urls')),
    path('api-auth/', include('rest_framework.urls')),
    # Serve uploaded media files in all environments (dev and production)
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
