from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db.models import Count, Sum, Q
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import *
from .cms_serializers import *
from .cms_permissions import CmsRolePermission, CmsAdminOnly, IsCmsUser, get_user_role
from .cms_utils import audit, parse_chart_file, validate_chart_rows, publish_chart_upload, recalculate_certifications
from .cms_alerts import build_dashboard_alerts, summarize_alerts


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
class CmsLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username') or request.data.get('email')
        password = request.data.get('password')
        if not username or not password:
            return Response({'detail': 'Username/email and password are required.'}, status=400)
        user = authenticate(request, username=username, password=password)
        if user is None:
            try:
                candidate = User.objects.get(email__iexact=username)
                user = authenticate(request, username=candidate.username, password=password)
            except User.DoesNotExist:
                user = None
        if not user or not user.is_active:
            return Response({'detail': 'Invalid login details.'}, status=400)
        login(request, user)
        AdminProfile.objects.get_or_create(user=user, defaults={'role': AdminRole.SUPER_ADMIN if user.is_superuser else AdminRole.VIEWER})
        audit(request, 'login', module='auth', obj=user)
        return Response({'user': CmsMeSerializer(user).data, 'csrfToken': get_token(request)})


class StorageDebugView(APIView):
    """Returns storage/Cloudinary configuration status — for diagnosing image upload issues."""
    permission_classes = [IsCmsUser]

    def get(self, request):
        from django.conf import settings as dj_settings
        import cloudinary
        cfg = cloudinary.config()
        return Response({
            'DEFAULT_FILE_STORAGE': dj_settings.DEFAULT_FILE_STORAGE if hasattr(dj_settings, 'DEFAULT_FILE_STORAGE') else 'django.core.files.storage.FileSystemStorage (default)',
            'CLOUDINARY_URL_SET': bool(getattr(dj_settings, 'CLOUDINARY_URL', '')),
            'cloudinary_cloud_name': getattr(cfg, 'cloud_name', None),
            'cloudinary_api_key_set': bool(getattr(cfg, 'api_key', None)),
            'cloudinary_api_secret_set': bool(getattr(cfg, 'api_secret', None)),
        })


class CsrfTokenView(APIView):
    """Returns the CSRF token for cross-domain CMS frontends that cannot read the cookie directly."""
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({'csrfToken': get_token(request)})


@method_decorator(csrf_exempt, name='dispatch')
class CmsLogoutView(APIView):
    permission_classes = [IsCmsUser]

    def post(self, request):
        audit(request, 'logout', module='auth', obj=request.user)
        logout(request)
        return Response({'ok': True})


class CmsMeView(APIView):
    permission_classes = [IsCmsUser]

    def get(self, request):
        profile, _ = AdminProfile.objects.get_or_create(user=request.user)
        profile.last_seen_at = timezone.now()
        profile.save(update_fields=['last_seen_at'])
        return Response({'user': CmsMeSerializer(request.user).data})


class CmsDashboardView(APIView):
    permission_classes = [IsCmsUser]

    def get(self, request):
        latest_chart = MonthlyChart.objects.order_by('-year', '-month').first()
        missing_artist_countries = Artist.objects.filter(Q(country='') & Q(country_code='')).count()
        duplicate_groups = duplicate_artist_groups(limit=50)
        pending_uploads = ChartUpload.objects.filter(status__in=['draft', 'pending_review']).count()
        alerts = build_dashboard_alerts(request.user)
        alert_summary = summarize_alerts(alerts)
        system_health = 'ACTION_REQUIRED' if alert_summary['error'] else ('NEEDS_ATTENTION' if alert_summary['warning'] else 'OK')
        data = {
            'cards': {
                'total_songs': Release.objects.filter(chart_type=ChartType.SINGLES).count(),
                'total_albums': Release.objects.filter(chart_type=ChartType.ALBUMS).count(),
                'total_artists': Artist.objects.count(),
                'latest_uploaded_chart_month': latest_chart.label if latest_chart else 'None',
                'pending_approvals': ChartUpload.objects.filter(status='pending_review').count() + NewsArticle.objects.filter(status='pending_review').count(),
                'missing_artist_countries': missing_artist_countries,
                'duplicate_artists_detected': len(duplicate_groups),
                'latest_news_posts': NewsArticle.objects.count(),
                'recently_edited_data': AuditLog.objects.count(),
                'errors_warnings': DataQualityIssue.objects.filter(status='open').count(),
                'system_health': system_health,
                'last_backup_date': BackupRecord.objects.order_by('-created_at').values_list('created_at', flat=True).first(),
                'editors_admins': AdminProfile.objects.exclude(role=AdminRole.VIEWER).count(),
                'unpublished_chart_months': MonthlyChart.objects.filter(is_published=False).count(),
                'certifications_unofficial': Certification.objects.filter(is_official=False, is_hidden=False).count(),
                'uploads_awaiting_review': pending_uploads,
            },
            'alerts': alerts,
            'alert_summary': alert_summary,
            'top_performing': list(MonthlyChartEntry.objects.filter(platform__isnull=True).values('release__title', 'release__artist__name').annotate(points=Sum('total_points')).order_by('-points')[:10]),
            'recent_activity': AuditLogSerializer(AuditLog.objects.select_related('user')[:12], many=True).data,
            'duplicate_artist_groups': duplicate_groups[:10],
        }
        return Response(data)


class CmsBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [CmsRolePermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def perform_create(self, serializer):
        obj = serializer.save()
        audit(self.request, 'created', module=getattr(self, 'module_name', ''), obj=obj, new=serializer.data)

    def perform_update(self, serializer):
        old = model_to_dict_safe(serializer.instance)
        obj = serializer.save()
        audit(self.request, 'updated', module=getattr(self, 'module_name', ''), obj=obj, old=old, new=serializer.data)

    def perform_destroy(self, instance):
        if hasattr(instance, 'status'):
            instance.status = 'archived'
            instance.save(update_fields=['status'])
            audit(self.request, 'archived', module=getattr(self, 'module_name', ''), obj=instance)
        elif hasattr(instance, 'is_archived'):
            instance.is_archived = True
            instance.save(update_fields=['is_archived'])
            audit(self.request, 'archived', module=getattr(self, 'module_name', ''), obj=instance)
        else:
            audit(self.request, 'deleted', module=getattr(self, 'module_name', ''), obj=instance)
            instance.delete()


class CmsUserViewSet(CmsBaseViewSet):
    queryset = User.objects.select_related('cms_profile').all().order_by('username')
    serializer_class = CmsUserSerializer
    permission_classes = [CmsAdminOnly]
    search_fields = ['username', 'email', 'first_name', 'last_name']
    module_name = 'users'


class CmsArtistViewSet(CmsBaseViewSet):
    queryset = Artist.objects.all()
    serializer_class = CmsArtistSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = ['name', 'display_name', 'aliases', 'country', 'country_code', 'genre']
    ordering_fields = ['name', 'country', 'created_at', 'updated_at']
    module_name = 'artists'

    def get_queryset(self):
        qs = super().get_queryset()
        missing_country = self.request.query_params.get('missing_country')
        if missing_country in {'1', 'true', 'yes'}:
            qs = qs.filter(Q(country='') & Q(country_code=''))
        return qs

    def perform_update(self, serializer):
        old_country = serializer.instance.country
        old_country_code = serializer.instance.country_code
        old = model_to_dict_safe(serializer.instance)
        obj = serializer.save()
        # Cascade country changes to releases that still carry the old artist country
        # (releases that had an explicitly different country are left untouched).
        new_country = obj.country
        new_country_code = obj.country_code
        if new_country != old_country or new_country_code != old_country_code:
            # Match releases by exact old country values, plus releases that have the
            # old country name but a missing code (those were never fully populated).
            code_filter = Q(country_code=old_country_code)
            if old_country and old_country_code:
                code_filter |= Q(country_code='')
            Release.objects.filter(
                artist=obj,
                country=old_country,
            ).filter(code_filter).update(
                country=new_country, country_code=new_country_code, updated_at=timezone.now()
            )
        audit(self.request, 'updated', module=self.module_name, obj=obj, old=old, new=serializer.data)

    @action(detail=False, methods=['get'])
    def missing_countries(self, request):
        qs = self.get_queryset().filter(Q(country='') & Q(country_code=''))[:250]
        return Response(CmsArtistSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'])
    def duplicates(self, request):
        return Response({'groups': duplicate_artist_groups(limit=200)})

    @action(detail=False, methods=['get'])
    def options(self, request):
        """Lightweight complete artist list used by ordered release-credit selectors."""
        artists = Artist.objects.exclude(status='archived').order_by('name').values(
            'id', 'name', 'display_name', 'country_code'
        )
        return Response([
            {
                'value': artist['id'],
                'label': artist['display_name'] or artist['name'],
                'country_code': artist['country_code'],
            }
            for artist in artists
        ])

    @action(detail=True, methods=['post'])
    def merge(self, request, pk=None):
        primary = self.get_object()
        ids = request.data.get('artist_ids') or []
        aliases = set(primary.aliases or [])
        moved = 0
        for artist in Artist.objects.filter(id__in=ids).exclude(id=primary.id):
            aliases.add(artist.name)
            for alias in artist.aliases or []:
                aliases.add(alias)
            moved += artist.releases.update(artist=primary)
            ArtistMergeLog.objects.create(primary_artist=primary, merged_artist_name=artist.name, merged_artist_id=artist.id, moved_releases=moved, aliases_added=list(aliases), merged_by=request.user)
            artist.status = 'archived'
            artist.name = f'{artist.name} (merged {artist.id})'
            artist.slug = f'{artist.slug}-merged-{artist.id}'[:50]
            artist.save(update_fields=['name', 'slug', 'status', 'updated_at'])
        primary.aliases = sorted(aliases)
        primary.save(update_fields=['aliases', 'updated_at'])
        audit(request, 'merged_artists', module='artists', obj=primary, new={'merged_ids': ids})
        return Response(CmsArtistSerializer(primary).data)

    @action(detail=False, methods=['post'])
    def bulk_country_update(self, request):
        ids = request.data.get('artist_ids') or []
        country = request.data.get('country', '')
        country_code = (request.data.get('country_code') or '')[:2].upper()
        # Cascade to releases: update releases where country matched the artist's old country.
        for artist in Artist.objects.filter(id__in=ids).only('id', 'country', 'country_code'):
            Release.objects.filter(
                artist=artist,
                country=artist.country,
                country_code=artist.country_code,
            ).update(country=country, country_code=country_code, updated_at=timezone.now())
        updated = Artist.objects.filter(id__in=ids).update(country=country, country_code=country_code, updated_at=timezone.now())
        audit(request, 'bulk_country_update', module='artists', new={'updated': updated, 'country': country, 'country_code': country_code})
        return Response({'updated': updated})


class CmsReleaseViewSet(CmsBaseViewSet):
    queryset = Release.objects.select_related('artist').prefetch_related('artist_credits__artist').all()
    serializer_class = CmsReleaseSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = ['title', 'artist__name', 'featured_artists', 'isrc', 'upc', 'country', 'country_code', 'genre', 'label']
    ordering_fields = ['title', 'chart_type', 'release_year', 'updated_at']
    module_name = 'releases'

    def get_queryset(self):
        qs = super().get_queryset()
        chart_type = self.request.query_params.get('chart_type')
        if chart_type:
            qs = qs.filter(chart_type=chart_type)
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class CmsCountryViewSet(CmsBaseViewSet):
    queryset = Country.objects.all()
    serializer_class = CmsCountrySerializer
    search_fields = ['name', 'code', 'region']
    module_name = 'countries'


class CmsPlatformViewSet(CmsBaseViewSet):
    queryset = Platform.objects.all()
    serializer_class = CmsPlatformSerializer
    search_fields = ['name', 'slug', 'short_name']
    module_name = 'platforms'


class CmsMonthlyChartViewSet(CmsBaseViewSet):
    queryset = MonthlyChart.objects.all()
    serializer_class = CmsMonthlyChartSerializer
    search_fields = ['label', 'chart_type', 'status']
    module_name = 'charts'

    @action(detail=True, methods=['get'])
    def entries(self, request, pk=None):
        chart = self.get_object()
        platform_id = request.query_params.get('platform')
        qs = chart.entries.select_related('release', 'release__artist', 'platform')
        if platform_id == 'combined':
            qs = qs.filter(platform__isnull=True)
        elif platform_id:
            qs = qs.filter(platform_id=platform_id)
        return Response(CmsMonthlyChartEntrySerializer(qs.order_by('rank'), many=True).data)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        chart = self.get_object()
        chart.is_published = True
        chart.status = 'published'
        chart.published_by = request.user
        chart.published_at = timezone.now()
        chart.save(update_fields=['is_published', 'status', 'published_by', 'published_at', 'updated_at'])
        audit(request, 'published_chart', module='charts', obj=chart)
        return Response(CmsMonthlyChartSerializer(chart).data)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        chart = self.get_object()
        chart.is_published = False
        chart.status = 'draft'
        chart.save(update_fields=['is_published', 'status', 'updated_at'])
        audit(request, 'unpublished_chart', module='charts', obj=chart)
        return Response(CmsMonthlyChartSerializer(chart).data)

    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        chart = self.get_object()
        chart.locked = True
        chart.save(update_fields=['locked', 'updated_at'])
        audit(request, 'locked_chart', module='charts', obj=chart)
        return Response(CmsMonthlyChartSerializer(chart).data)


class CmsMonthlyChartEntryViewSet(CmsBaseViewSet):
    queryset = MonthlyChartEntry.objects.select_related(
        'chart', 'release', 'release__artist', 'platform'
    ).all()
    serializer_class = CmsMonthlyChartEntrySerializer
    search_fields = ['release__title', 'release__artist__name', 'featured_artists']
    ordering_fields = ['rank', 'total_points', 'weeks_on_chart']
    module_name = 'chart_entries'

    def get_queryset(self):
        qs = super().get_queryset()
        chart_id = self.request.query_params.get('chart')
        platform = self.request.query_params.get('platform')
        if chart_id:
            qs = qs.filter(chart_id=chart_id)
        if platform == 'combined':
            qs = qs.filter(platform__isnull=True)
        elif platform:
            qs = qs.filter(platform_id=platform)
        return qs.order_by('rank')

    def _check_locked(self, chart):
        if chart.locked:
            raise DRFValidationError("This chart is locked and cannot be edited.")

    def perform_create(self, serializer):
        chart = serializer.validated_data.get('chart')
        if chart:
            self._check_locked(chart)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._check_locked(serializer.instance.chart)
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._check_locked(instance.chart)
        audit(self.request, 'deleted', module=self.module_name, obj=instance)
        instance.delete()

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Renumber all ranks for a chart/platform sequentially, preserving current order."""
        chart_id = request.data.get('chart')
        platform = request.data.get('platform')
        if not chart_id:
            return Response({'detail': 'chart is required.'}, status=400)
        try:
            chart = MonthlyChart.objects.get(pk=chart_id)
        except MonthlyChart.DoesNotExist:
            return Response({'detail': 'Chart not found.'}, status=404)
        self._check_locked(chart)
        qs = MonthlyChartEntry.objects.filter(chart=chart)
        if platform == 'combined':
            qs = qs.filter(platform__isnull=True)
        elif platform:
            qs = qs.filter(platform_id=platform)
        entries = list(qs.order_by('rank'))
        for i, entry in enumerate(entries, 1):
            if entry.rank != i:
                entry.rank = i
                entry.save(update_fields=['rank'])
        audit(request, 'reordered_entries', module=self.module_name, new={'chart_id': chart_id, 'count': len(entries)})
        return Response({'reordered': len(entries)})


class ChartUploadViewSet(CmsBaseViewSet):
    queryset = ChartUpload.objects.select_related('platform', 'uploaded_by', 'approved_by', 'published_by').all()
    serializer_class = ChartUploadSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = ['original_filename', 'status', 'chart_type', 'notes']
    module_name = 'chart_uploads'

    def perform_create(self, serializer):
        upload = serializer.save(uploaded_by=self.request.user, original_filename=getattr(self.request.FILES.get('file'), 'name', ''))
        self._parse_and_validate(upload)
        audit(self.request, 'uploaded_chart_file', module='uploads', obj=upload, new={'rows': upload.row_count, 'summary': upload.validation_summary})

    def _parse_and_validate(self, upload):
        if upload.file:
            upload.file.open('rb')
            rows = parse_chart_file(upload.file)
            upload.file.close()
        else:
            rows = upload.rows_data or []
        summary = validate_chart_rows(rows, chart_type=upload.chart_type, platform=upload.platform, year=upload.year, month=upload.month)
        upload.rows_data = rows
        upload.row_count = len(rows)
        upload.validation_summary = summary
        upload.save(update_fields=['rows_data', 'row_count', 'validation_summary', 'updated_at'])
        return summary

    @action(detail=True, methods=['post'])
    def revalidate(self, request, pk=None):
        upload = self.get_object()
        summary = self._parse_and_validate(upload)
        audit(request, 'revalidated_upload', module='uploads', obj=upload, new=summary)
        return Response(ChartUploadSerializer(upload).data)

    @action(detail=True, methods=['patch'])
    def rows(self, request, pk=None):
        upload = self.get_object()
        upload.rows_data = request.data.get('rows', upload.rows_data)
        upload.validation_summary = validate_chart_rows(upload.rows_data, chart_type=upload.chart_type, platform=upload.platform, year=upload.year, month=upload.month)
        upload.row_count = len(upload.rows_data)
        upload.save(update_fields=['rows_data', 'validation_summary', 'row_count', 'updated_at'])
        audit(request, 'edited_upload_rows', module='uploads', obj=upload)
        return Response(ChartUploadSerializer(upload).data)

    @action(detail=True, methods=['post'])
    def submit_review(self, request, pk=None):
        upload = self.get_object()
        upload.status = 'pending_review'
        upload.save(update_fields=['status', 'updated_at'])
        audit(request, 'submitted_upload_review', module='uploads', obj=upload)
        return Response(ChartUploadSerializer(upload).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        upload = self.get_object()
        upload.status = 'approved'
        upload.approved_by = request.user
        upload.approved_at = timezone.now()
        upload.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        audit(request, 'approved_upload', module='uploads', obj=upload)
        return Response(ChartUploadSerializer(upload).data)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        upload = self.get_object()
        if not upload.validation_summary.get('can_publish'):
            return Response({'detail': 'Fix validation errors before publishing.', 'validation': upload.validation_summary}, status=400)
        chart, count = publish_chart_upload(upload, user=request.user)
        audit(request, 'published_upload', module='uploads', obj=upload, new={'chart_id': chart.id, 'entries': count})
        return Response({'upload': ChartUploadSerializer(upload).data, 'chart': CmsMonthlyChartSerializer(chart).data, 'entries_created': count})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        upload = self.get_object()
        upload.status = 'rejected'
        upload.notes = f"{upload.notes}\nRejected: {request.data.get('reason','') }".strip()
        upload.save(update_fields=['status', 'notes', 'updated_at'])
        audit(request, 'rejected_upload', module='uploads', obj=upload, reason=request.data.get('reason', ''))
        return Response(ChartUploadSerializer(upload).data)

    @action(detail=True, methods=['post'])
    def rollback(self, request, pk=None):
        upload = self.get_object()
        MonthlyChartEntry.objects.filter(chart__year=upload.year, chart__month=upload.month, chart__chart_type=upload.chart_type, platform=upload.platform).delete()
        upload.status = 'rolled_back'
        upload.save(update_fields=['status', 'updated_at'])
        audit(request, 'rolled_back_upload', module='uploads', obj=upload)
        return Response(ChartUploadSerializer(upload).data)


class CmsNewsArticleViewSet(CmsBaseViewSet):
    queryset = NewsArticle.objects.all()
    serializer_class = CmsNewsArticleSerializer
    search_fields = ['title', 'subheadline', 'excerpt', 'body', 'category', 'author']
    module_name = 'news'

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        article = self.get_object()
        article.status = 'published'
        article.is_published = True
        article.published_at = timezone.now()
        article.save(update_fields=['status', 'is_published', 'published_at', 'updated_at'])
        audit(request, 'published_article', module='news', obj=article)
        return Response(CmsNewsArticleSerializer(article).data)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        article = self.get_object()
        article.status = 'draft'
        article.is_published = False
        article.save(update_fields=['status', 'is_published', 'updated_at'])
        audit(request, 'unpublished_article', module='news', obj=article)
        return Response(CmsNewsArticleSerializer(article).data)


class CmsMediaAssetViewSet(CmsBaseViewSet):
    queryset = MediaAsset.objects.all()
    serializer_class = MediaAssetSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = ['title', 'folder', 'alt_text', 'usage_notes']
    module_name = 'media'

    def perform_create(self, serializer):
        obj = serializer.save(uploaded_by=self.request.user)
        audit(self.request, 'uploaded_media', module='media', obj=obj)


class CmsSiteSettingViewSet(CmsBaseViewSet):
    queryset = SiteSetting.objects.all()
    serializer_class = SiteSettingSerializer
    search_fields = ['key', 'group', 'description']
    module_name = 'settings'

    def perform_create(self, serializer):
        obj = serializer.save(updated_by=self.request.user)
        audit(self.request, 'created_setting', module='settings', obj=obj, new=serializer.data)

    def perform_update(self, serializer):
        old = model_to_dict_safe(serializer.instance)
        obj = serializer.save(updated_by=self.request.user)
        audit(self.request, 'updated_setting', module='settings', obj=obj, old=old, new=serializer.data)


class CmsPageContentViewSet(CmsBaseViewSet):
    queryset = PageContent.objects.all()
    serializer_class = PageContentSerializer
    search_fields = ['page', 'section', 'title', 'content']
    module_name = 'page_content'


class CmsCertificationViewSet(CmsBaseViewSet):
    queryset = Certification.objects.select_related('release', 'release__artist').all()
    serializer_class = CmsCertificationSerializer
    search_fields = ['release__title', 'release__artist__name', 'level']
    module_name = 'certifications'

    @action(detail=False, methods=['post'])
    def recalculate(self, request):
        count = recalculate_certifications(chart_type=request.data.get('chart_type'))
        audit(request, 'recalculated_certifications', module='certifications', new={'count': count})
        return Response({'updated_or_created': count})


class CertificationRuleViewSet(CmsBaseViewSet):
    queryset = CertificationRule.objects.all()
    serializer_class = CertificationRuleSerializer
    module_name = 'certification_rules'


class MethodologySettingViewSet(CmsBaseViewSet):
    queryset = MethodologySetting.objects.all()
    serializer_class = MethodologySettingSerializer
    search_fields = ['version', 'name']
    module_name = 'methodology'


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsCmsUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['action', 'module', 'object_type', 'object_repr', 'user__username', 'reason']
    ordering_fields = ['created_at', 'module', 'action']


class InternalNoteViewSet(CmsBaseViewSet):
    queryset = InternalNote.objects.select_related('created_by').all()
    serializer_class = InternalNoteSerializer
    search_fields = ['module', 'object_id', 'note']
    module_name = 'notes'

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        audit(self.request, 'created_note', module='notes', obj=obj)


class AdminNotificationViewSet(CmsBaseViewSet):
    serializer_class = AdminNotificationSerializer
    search_fields = ['title', 'message', 'module']
    module_name = 'notifications'

    def get_queryset(self):
        return AdminNotification.objects.filter(Q(user=self.request.user) | Q(user__isnull=True))

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        count = self.get_queryset().update(is_read=True)
        return Response({'updated': count})


class BackupRecordViewSet(CmsBaseViewSet):
    queryset = BackupRecord.objects.all()
    serializer_class = BackupRecordSerializer
    permission_classes = [CmsAdminOnly]
    module_name = 'backups'


class DataQualityIssueViewSet(CmsBaseViewSet):
    queryset = DataQualityIssue.objects.all()
    serializer_class = DataQualityIssueSerializer
    search_fields = ['module', 'issue_type', 'description', 'severity', 'status']
    module_name = 'reports'


class PlaceholderModuleViewSet(CmsBaseViewSet):
    queryset = PlaceholderModule.objects.all()
    serializer_class = PlaceholderModuleSerializer
    search_fields = ['module', 'title', 'status']
    module_name = 'future_modules'


class GlobalSearchView(APIView):
    permission_classes = [IsCmsUser]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if not q:
            return Response({'results': []})
        results = []
        for artist in Artist.objects.filter(Q(name__icontains=q) | Q(display_name__icontains=q))[:8]:
            results.append({'type': 'artist', 'id': artist.id, 'title': artist.name, 'subtitle': artist.country})
        for release in Release.objects.select_related('artist').filter(Q(title__icontains=q) | Q(artist__name__icontains=q))[:8]:
            results.append({'type': release.chart_type, 'id': release.id, 'title': release.title, 'subtitle': release.artist.name})
        for article in NewsArticle.objects.filter(Q(title__icontains=q) | Q(body__icontains=q))[:8]:
            results.append({'type': 'news', 'id': article.id, 'title': article.title, 'subtitle': article.category})
        for cert in Certification.objects.select_related('release', 'release__artist').filter(Q(release__title__icontains=q) | Q(release__artist__name__icontains=q))[:8]:
            results.append({'type': 'certification', 'id': cert.id, 'title': f'{cert.release.title} — {cert.level}', 'subtitle': cert.release.artist.name})
        return Response({'results': results})


def duplicate_artist_groups(limit=100):
    artists = Artist.objects.all().only('id', 'name', 'country', 'country_code', 'aliases')
    buckets = {}
    for artist in artists:
        key = normalize_artist_key(artist.name)
        buckets.setdefault(key, []).append({'id': artist.id, 'name': artist.name, 'country': artist.country, 'country_code': artist.country_code})
    groups = [items for items in buckets.values() if len(items) > 1]
    groups.sort(key=len, reverse=True)
    return groups[:limit]


def normalize_artist_key(name):
    import unicodedata, re
    value = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^a-z0-9]+', '', value.lower())
    value = value.replace('aime', 'aime')
    return value


def model_to_dict_safe(instance):
    data = {}
    for field in instance._meta.fields:
        value = getattr(instance, field.name, None)
        if field.get_internal_type() in {'FileField', 'ImageField'}:
            value = getattr(value, 'name', '') or ''
        elif hasattr(value, 'pk'):
            value = value.pk
        elif hasattr(value, 'isoformat'):
            value = value.isoformat()
        data[field.name] = value
    return data
