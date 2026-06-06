from rest_framework.routers import DefaultRouter  # type: ignore[import]
from . import views

router = DefaultRouter()
router.register('platforms', views.PlatformViewSet)
router.register('artists', views.ArtistViewSet)
router.register('releases', views.ReleaseViewSet)
router.register('charts', views.MonthlyChartViewSet)
router.register('uploads', views.WeeklyUploadViewSet)
router.register('news', views.NewsArticleViewSet)
router.register('certifications', views.CertificationViewSet)
router.register('normalization-rules', views.NormalizationRuleViewSet)

from django.urls import path
from .ai_analyst import ai_analyst

urlpatterns = router.urls + [
       path('ai/analyst/', ai_analyst),
   ]