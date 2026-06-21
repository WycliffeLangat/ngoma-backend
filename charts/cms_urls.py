from django.urls import path
from rest_framework.routers import DefaultRouter
from . import cms_views

router = DefaultRouter()
router.register('users', cms_views.CmsUserViewSet, basename='cms-users')
router.register('artists', cms_views.CmsArtistViewSet, basename='cms-artists')
router.register('releases', cms_views.CmsReleaseViewSet, basename='cms-releases')
router.register('countries', cms_views.CmsCountryViewSet, basename='cms-countries')
router.register('platforms', cms_views.CmsPlatformViewSet, basename='cms-platforms')
router.register('charts', cms_views.CmsMonthlyChartViewSet, basename='cms-charts')
router.register('chart-entries', cms_views.CmsMonthlyChartEntryViewSet, basename='cms-chart-entries')
router.register('chart-uploads', cms_views.ChartUploadViewSet, basename='cms-chart-uploads')
router.register('news', cms_views.CmsNewsArticleViewSet, basename='cms-news')
router.register('media', cms_views.CmsMediaAssetViewSet, basename='cms-media')
router.register('settings', cms_views.CmsSiteSettingViewSet, basename='cms-settings')
router.register('page-content', cms_views.CmsPageContentViewSet, basename='cms-page-content')
router.register('certifications', cms_views.CmsCertificationViewSet, basename='cms-certifications')
router.register('certification-rules', cms_views.CertificationRuleViewSet, basename='cms-certification-rules')
router.register('methodology', cms_views.MethodologySettingViewSet, basename='cms-methodology')
router.register('audit-logs', cms_views.AuditLogViewSet, basename='cms-audit-logs')
router.register('notes', cms_views.InternalNoteViewSet, basename='cms-notes')
router.register('notifications', cms_views.AdminNotificationViewSet, basename='cms-notifications')
router.register('backups', cms_views.BackupRecordViewSet, basename='cms-backups')
router.register('reports', cms_views.DataQualityIssueViewSet, basename='cms-reports')
router.register('future-modules', cms_views.PlaceholderModuleViewSet, basename='cms-future-modules')

urlpatterns = [
    path('auth/login/', cms_views.CmsLoginView.as_view()),
    path('auth/logout/', cms_views.CmsLogoutView.as_view()),
    path('auth/me/', cms_views.CmsMeView.as_view()),
    path('csrf/', cms_views.CsrfTokenView.as_view()),
    path('dashboard/', cms_views.CmsDashboardView.as_view()),
    path('search/', cms_views.GlobalSearchView.as_view()),
    path('debug/storage/', cms_views.StorageDebugView.as_view()),
] + router.urls
