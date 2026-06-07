from rest_framework.routers import DefaultRouter
from django.urls import path

from . import views
from .ai_analyst import ai_analyst
from .chart_export import chart_image_data

router = DefaultRouter()
router.register('platforms', views.PlatformViewSet)
router.register('artists', views.ArtistViewSet)
router.register('releases', views.ReleaseViewSet)
router.register('charts', views.MonthlyChartViewSet)
router.register('uploads', views.WeeklyUploadViewSet)
router.register('news', views.NewsArticleViewSet)
router.register('certifications', views.CertificationViewSet)
router.register('normalization-rules', views.NormalizationRuleViewSet)

urlpatterns = router.urls + [
    path('ai/analyst/', ai_analyst),
    path('export/chart-image-data/', chart_image_data),
]