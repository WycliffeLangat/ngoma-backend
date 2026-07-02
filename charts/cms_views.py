from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Min, Sum, Q
from django.db.models.functions import Coalesce
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import *
from .cms_serializers import *
from .cms_permissions import CmsRolePermission, CmsAdminOnly, IsCmsUser, get_user_role
from .cms_utils import audit, bump_public_revision, parse_chart_file, validate_chart_rows, publish_chart_upload, recalculate_certifications, harmonize_chart_history, published_top50_entries
from .models import PlatformChartEntry
from .cms_alerts import build_dashboard_alerts, summarize_alerts
from .pipeline import process_weekly_upload, rebuild_monthly_chart


def _chart_ids_for_artists(artist_ids):
    """Charts containing any monthly entry for a release credited (primary
    or featured) to any of `artist_ids`.

    Platform-only releases must be included because country-scoped charts can
    contain candidates outside the global Combined Top 50.
    """
    return list(
        MonthlyChartEntry.objects.filter(
            Q(release__artist__in=artist_ids) | Q(release__artist_credits__artist__in=artist_ids)
        )
        .values_list('chart_id', flat=True).distinct()
    )


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
    permission_classes = [CmsAdminOnly]

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
        revision = AuditLog.objects.exclude(module='auth').values_list('id', flat=True).first() or 0
        cache_key = f'cms_dashboard_summary:{revision}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        latest_chart = MonthlyChart.objects.order_by('-year', '-month').first()
        release_counts = {
            row['chart_type']: row['count']
            for row in Release.objects.values('chart_type').annotate(count=Count('id'))
        }
        data = {
            'cards': {
                'total_songs': release_counts.get(ChartType.SINGLES, 0),
                'total_albums': release_counts.get(ChartType.ALBUMS, 0),
                'total_artists': Artist.objects.count(),
                'latest_uploaded_chart_month': latest_chart.label if latest_chart else 'None',
                'pending_approvals': ChartUpload.objects.filter(status='pending_review').count() + NewsArticle.objects.filter(status='pending_review').count(),
                'errors_warnings': DataQualityIssue.objects.filter(status='open').count(),
                'unpublished_chart_months': MonthlyChart.objects.filter(is_published=False).count(),
            },
        }
        cache.set(cache_key, data, 60)
        return Response(data)


class CmsDashboardInsightsView(APIView):
    permission_classes = [IsCmsUser]

    def get(self, request):
        revision = AuditLog.objects.exclude(module='auth').values_list('id', flat=True).first() or 0
        cache_key = f'cms_dashboard_insights:{get_user_role(request.user)}:{revision}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        alerts = build_dashboard_alerts(request.user)
        alert_summary = summarize_alerts(alerts)
        duplicate_count = next(
            (a['count'] for a in alerts if a['id'] == 'possible-duplicate-artists'), 0
        )
        system_health = (
            'ACTION_REQUIRED' if alert_summary['error']
            else ('NEEDS_ATTENTION' if alert_summary['warning'] else 'OK')
        )
        data = {
            'alerts': alerts,
            'alert_summary': alert_summary,
            'cards': {
                'missing_artist_countries': Artist.objects.filter(Q(country='') & Q(country_code='')).count(),
                'duplicate_artists_detected': duplicate_count,
                'latest_news_posts': NewsArticle.objects.count(),
                'recently_edited_data': AuditLog.objects.count(),
                'system_health': system_health,
                'last_backup_date': BackupRecord.objects.order_by('-created_at').values_list('created_at', flat=True).first(),
                'editors_admins': AdminProfile.objects.exclude(role=AdminRole.VIEWER).count(),
                'certifications_unofficial': Certification.objects.filter(is_official=False, is_hidden=False).count(),
                'uploads_awaiting_review': ChartUpload.objects.filter(status__in=['draft', 'pending_review']).count(),
            },
            'top_performing': list(
                published_top50_entries()
                .values('release__title', 'release__artist__name')
                .annotate(points=Sum('total_points'))
                .order_by('-points')[:10]
            ),
            'recent_activity': AuditLogSerializer(
                AuditLog.objects.select_related('user')[:12], many=True
            ).data,
        }
        cache.set(cache_key, data, 120)
        return Response(data)


class CmsPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class CmsBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [CmsRolePermission]
    pagination_class = CmsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def get_queryset(self):
        qs = super().get_queryset()
        starts_with = self.request.query_params.get('starts_with', '').strip()
        if starts_with and len(starts_with) == 1 and starts_with.isalpha():
            # Use explicit starts_with_field, or the first search field without relation traversal
            sw_field = getattr(self, 'starts_with_field', None)
            if not sw_field:
                for f in getattr(self, 'search_fields', []):
                    if '__' not in f:
                        sw_field = f
                        break
            if sw_field:
                qs = qs.filter(**{f'{sw_field}__istartswith': starts_with})
        return qs

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

    @action(detail=True, methods=['delete'], url_path='hard_delete')
    def hard_delete(self, request, pk=None):
        obj = self.get_object()
        obj_repr = str(obj)
        obj_id = obj.pk
        with transaction.atomic():
            obj.delete()
        audit(request, 'hard_deleted', module=getattr(self, 'module_name', ''), new={
            'id': obj_id, 'repr': obj_repr,
        })
        bump_public_revision()
        return Response({'deleted': True}, status=200)


class CmsUserViewSet(CmsBaseViewSet):
    queryset = User.objects.select_related('cms_profile').all().order_by('username')
    serializer_class = CmsUserSerializer
    permission_classes = [CmsAdminOnly]
    search_fields = ['username', 'email', 'first_name', 'last_name']
    module_name = 'users'


class CmsArtistViewSet(CmsBaseViewSet):
    _public_credit_filter = Q(
        release_credits__release__monthlychartentry__chart__is_published=True,
        release_credits__release__monthlychartentry__chart__status='published',
        release_credits__release__monthlychartentry__platform__isnull=True,
        release_credits__release__monthlychartentry__rank__range=(1, 50),
    )
    queryset = Artist.objects.annotate(
        cms_total_releases=Count('release_credits__release', distinct=True),
        cms_total_points=Coalesce(Sum('release_credits__release__monthlychartentry__total_points', filter=_public_credit_filter), 0),
        cms_peak_rank=Min('release_credits__release__monthlychartentry__rank', filter=_public_credit_filter),
        cms_months_on_chart=Count('release_credits__release__monthlychartentry__chart', filter=_public_credit_filter, distinct=True),
        cms_entry_count=Count('release_credits__release__monthlychartentry', filter=_public_credit_filter, distinct=True),
    ).order_by('name')
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
            # Artist country is authoritative for chart eligibility, so every
            # chart this artist appears on (primary or featured) needs
            # re-evaluating for country-scoped charts (e.g. Kenya) —
            # not just the releases the cascade above touched.
            chart_ids = _chart_ids_for_artists([obj.id])
            if chart_ids:
                harmonize_chart_history(chart_ids=chart_ids)
        audit(self.request, 'updated', module=self.module_name, obj=obj, old=old, new=serializer.data)

    @action(detail=False, methods=['get'])
    def missing_countries(self, request):
        qs = self.get_queryset().filter(Q(country='') & Q(country_code=''))[:250]
        return Response(CmsArtistSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'])
    def duplicates(self, request):
        return Response({'groups': duplicate_artist_groups(limit=200)})

    @action(detail=True, methods=['delete'], url_path='hard_delete')
    def hard_delete(self, request, pk=None):
        artist = self.get_object()
        active_count = Release.objects.filter(artist=artist).exclude(status='archived').count()
        if active_count > 0:
            return Response({
                'detail': (
                    f'Cannot delete: this artist has {active_count} active release(s). '
                    'Merge the artist first so their releases are reassigned.'
                ),
                'release_count': active_count,
            }, status=400)
        artist_repr = str(artist)
        artist_id = artist.pk
        artist.delete()
        audit(request, 'hard_deleted', module='artists', new={'id': artist_id, 'repr': artist_repr})
        bump_public_revision()
        return Response({'deleted': True}, status=200)

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
        with transaction.atomic():
            for artist in Artist.objects.filter(id__in=ids).exclude(id=primary.id):
                aliases.add(artist.name)
                for alias in artist.aliases or []:
                    aliases.add(alias)

                # Release.unique_together = ['canonical_title', 'artist', 'chart_type']
                # Rebuild primary_canonical each iteration so releases moved from
                # previous dup artists are visible and avoid IntegrityErrors on
                # bulk FK update.
                primary_canonical = {
                    (r.canonical_title, r.chart_type): r
                    for r in Release.objects.filter(artist=primary).only('id', 'canonical_title', 'chart_type')
                }
                safe_ids = []
                for dup_rel in list(artist.releases.only('id', 'canonical_title', 'chart_type')):
                    key = (dup_rel.canonical_title, dup_rel.chart_type)
                    if key in primary_canonical:
                        keeper_rel = primary_canonical[key]
                        # Move/sum MCE entries
                        for entry in list(MonthlyChartEntry.objects.filter(release=dup_rel)):
                            ke = MonthlyChartEntry.objects.filter(
                                chart_id=entry.chart_id, platform_id=entry.platform_id, release=keeper_rel,
                            ).first()
                            if ke:
                                ke.total_points += entry.total_points
                                if entry.raw_total_points is not None:
                                    ke.raw_total_points = (ke.raw_total_points or 0) + entry.raw_total_points
                                ke.weeks_on_chart += entry.weeks_on_chart
                                ke.peak_rank = min(ke.peak_rank, entry.peak_rank)
                                ke.platform_count = max(ke.platform_count, entry.platform_count)
                                ke.platform_max = max(ke.platform_max, entry.platform_max)
                                ke.save(update_fields=[
                                    'total_points', 'raw_total_points', 'weeks_on_chart',
                                    'peak_rank', 'platform_count', 'platform_max',
                                ])
                                entry.delete()
                            else:
                                entry.release = keeper_rel
                                entry.save(update_fields=['release'])
                        # PCE: drop same-week+platform conflicts, move the rest
                        keeper_pce_pairs = set(
                            PlatformChartEntry.objects.filter(release=keeper_rel)
                            .values_list('upload_id', 'platform_id')
                        )
                        for pce in list(PlatformChartEntry.objects.filter(release=dup_rel)):
                            if (pce.upload_id, pce.platform_id) in keeper_pce_pairs:
                                pce.delete()
                            else:
                                pce.release = keeper_rel
                                pce.save(update_fields=['release'])
                        Certification.objects.filter(release=dup_rel).delete()
                        dup_rel.delete()
                        recalculate_certifications(release=keeper_rel)
                        moved += 1
                    else:
                        safe_ids.append(dup_rel.id)

                # Bulk-move releases that don't conflict
                if safe_ids:
                    moved += Release.objects.filter(pk__in=safe_ids).update(artist=primary)

                ArtistMergeLog.objects.create(
                    primary_artist=primary, merged_artist_name=artist.name,
                    merged_artist_id=artist.id, moved_releases=len(safe_ids) + moved,
                    aliases_added=list(aliases), merged_by=request.user,
                )
                artist.status = 'archived'
                artist.name = f'{artist.name} (merged {artist.id})'
                artist.slug = f'merged-{artist.id}'
                artist.save(update_fields=['name', 'slug', 'status', 'updated_at'])

            # Update aliases inside the transaction so it's atomic with archiving.
            primary.aliases = sorted(aliases)
            primary.save(update_fields=['aliases', 'updated_at'])

        audit(request, 'merged_artists', module='artists', obj=primary, new={'merged_ids': ids})
        bump_public_revision()
        primary.refresh_from_db()
        return Response(CmsArtistSerializer(primary, context={'request': request}).data)

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
        chart_ids = _chart_ids_for_artists(ids)
        if chart_ids:
            harmonize_chart_history(chart_ids=chart_ids)
        audit(request, 'bulk_country_update', module='artists', new={'updated': updated, 'country': country, 'country_code': country_code})
        return Response({'updated': updated})


class CmsReleaseViewSet(CmsBaseViewSet):
    _public_entry_filter = Q(
        monthlychartentry__chart__is_published=True,
        monthlychartentry__chart__status='published',
        monthlychartentry__platform__isnull=True,
        monthlychartentry__rank__range=(1, 50),
    )
    queryset = Release.objects.select_related('artist').prefetch_related(
        'artist_credits__artist', 'certifications'
    ).annotate(
        cms_total_points=Coalesce(Sum('monthlychartentry__total_points', filter=_public_entry_filter), 0),
        cms_peak_rank=Min('monthlychartentry__rank', filter=_public_entry_filter),
        cms_months_on_chart=Count('monthlychartentry__chart', filter=_public_entry_filter, distinct=True),
        cms_entry_count=Count('monthlychartentry', filter=_public_entry_filter, distinct=True),
    ).order_by('title')
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

    def perform_update(self, serializer):
        old_country = serializer.instance.country
        old_country_code = serializer.instance.country_code
        old = model_to_dict_safe(serializer.instance)
        obj = serializer.save()
        if obj.country != old_country or obj.country_code != old_country_code:
            chart_ids = list(
                MonthlyChartEntry.objects.filter(release=obj)
                .values_list('chart_id', flat=True).distinct()
            )
            if chart_ids:
                harmonize_chart_history(chart_ids=chart_ids)
        audit(self.request, 'updated', module=self.module_name, obj=obj, old=old, new=serializer.data)

    @action(detail=False, methods=['get'])
    def duplicates(self, request):
        """
        Return groups of 2+ releases that are likely duplicates.
        Uses simplified title matching (strips feat., punctuation, case) so near-matches
        like 'BackBencher' / 'Backbencher (feat. X)' land in the same group.
        Does NOT require the same artist_id — catches releases that drifted to different
        artist records after artist-alias cleanup.
        """
        import re, unicodedata
        chart_type = request.query_params.get('chart_type')
        qs = Release.objects.exclude(status='archived').select_related('artist')
        if chart_type:
            qs = qs.filter(chart_type=chart_type)

        def simplify(title):
            s = unicodedata.normalize('NFKD', str(title or '')).encode('ascii', 'ignore').decode('ascii')
            s = s.lower()
            s = re.sub(r'\s*[\(\[]\s*(feat|ft|featuring|remix|remaster|remastered|live|acoustic|radio\s*edit|version)[^\)\]]*[\)\]]', '', s)
            s = re.sub(r'\s+(feat|ft|featuring)\b.*', '', s)
            s = re.sub(r'[^a-z0-9]', '', s)
            return s

        from collections import defaultdict
        groups = defaultdict(list)
        for r in qs.order_by('id'):
            key = (simplify(r.title), r.chart_type)
            groups[key].append(r)

        entry_counts_cache = {}
        def entry_count(r):
            if r.id not in entry_counts_cache:
                entry_counts_cache[r.id] = MonthlyChartEntry.objects.filter(release=r).count()
            return entry_counts_cache[r.id]

        result = []
        for releases in groups.values():
            if len(releases) < 2:
                continue
            result.append([
                {
                    'id': r.id,
                    'title': r.title,
                    'artist_display': r.artist.name,
                    'artist_id': r.artist_id,
                    'chart_type': r.chart_type,
                    'status': r.status,
                    'cover_image': r.cover_image.url if r.cover_image else None,
                    'entry_count': entry_count(r),
                }
                for r in sorted(releases, key=lambda x: (-bool(x.cover_image), -entry_count(x), x.id))
            ])

        result.sort(key=lambda g: g[0]['title'].lower())
        return Response({'groups': result, 'total': len(result)})

    @action(detail=True, methods=['post'])
    def merge(self, request, pk=None):
        """
        Merge this release (the duplicate) into another (the keeper).
        Body: { "into_id": <keeper_release_id> }
        MCE conflicts (same month + platform): points are SUMMED into keeper's entry.
        PCE conflicts (same week + platform): dup's entry is dropped (a song can only
        appear once per weekly chart per platform).
        """
        duplicate = self.get_object()
        into_id = request.data.get('into_id')
        if not into_id:
            return Response({'detail': 'into_id is required.'}, status=400)
        try:
            keeper = Release.objects.get(pk=into_id)
        except Release.DoesNotExist:
            return Response({'detail': f'Release {into_id} not found.'}, status=404)
        if keeper.pk == duplicate.pk:
            return Response({'detail': 'Cannot merge a release into itself.'}, status=400)

        with transaction.atomic():
            mce_moved = mce_summed = 0
            for entry in list(MonthlyChartEntry.objects.filter(release=duplicate)):
                keeper_entry = MonthlyChartEntry.objects.filter(
                    chart_id=entry.chart_id,
                    platform_id=entry.platform_id,
                    release=keeper,
                ).first()
                if keeper_entry:
                    # Same month + platform: sum the points instead of discarding
                    keeper_entry.total_points += entry.total_points
                    if entry.raw_total_points is not None:
                        keeper_entry.raw_total_points = (keeper_entry.raw_total_points or 0) + entry.raw_total_points
                    keeper_entry.weeks_on_chart += entry.weeks_on_chart
                    keeper_entry.peak_rank = min(keeper_entry.peak_rank, entry.peak_rank)
                    keeper_entry.platform_count = max(keeper_entry.platform_count, entry.platform_count)
                    keeper_entry.platform_max = max(keeper_entry.platform_max, entry.platform_max)
                    keeper_entry.save(update_fields=[
                        'total_points', 'raw_total_points', 'weeks_on_chart',
                        'peak_rank', 'platform_count', 'platform_max',
                    ])
                    entry.delete()
                    mce_summed += 1
                else:
                    mce_moved += 1
                    entry.release = keeper
                    entry.save(update_fields=['release'])

            # PCE: drop same-week + same-platform conflicts; move the rest.
            # A song should appear at most once per weekly chart per platform.
            keeper_pce_pairs = set(
                PlatformChartEntry.objects.filter(release=keeper).values_list('upload_id', 'platform_id')
            )
            pce_moved = pce_dropped = 0
            for pce in list(PlatformChartEntry.objects.filter(release=duplicate)):
                if (pce.upload_id, pce.platform_id) in keeper_pce_pairs:
                    pce.delete()
                    pce_dropped += 1
                else:
                    pce.release = keeper
                    pce.save(update_fields=['release'])
                    pce_moved += 1

            _META = ['cover_image','genre','label','distributor','isrc','upc','release_year',
                     'release_date','songwriters','producers',
                     'spotify_url','apple_music_url','youtube_url','boomplay_url','audiomack_url',
                     'tiktok_url','shazam_url','radio_info']
            updates = []
            for f in _META:
                if getattr(duplicate, f) and not getattr(keeper, f):
                    setattr(keeper, f, getattr(duplicate, f))
                    updates.append(f)
            if updates:
                keeper.save(update_fields=updates + ['updated_at'])

            Certification.objects.filter(release=duplicate).delete()
            dup_repr = str(duplicate)
            dup_id = duplicate.pk
            duplicate.delete()

        harmonize_chart_history(chart_type=keeper.chart_type)
        audit(request, 'merged_release', module='releases', obj=keeper, new={
            'merged_id': dup_id, 'merged_repr': dup_repr,
            'mce_moved': mce_moved, 'mce_summed': mce_summed, 'pce_moved': pce_moved, 'pce_dropped': pce_dropped,
        })
        bump_public_revision()
        keeper.refresh_from_db()
        return Response({
            'keeper': CmsReleaseSerializer(keeper, context={'request': request}).data,
            'mce_moved': mce_moved, 'mce_summed': mce_summed, 'pce_moved': pce_moved, 'pce_dropped': pce_dropped,
        })

    @action(detail=True, methods=['delete'], url_path='hard_delete')
    def hard_delete(self, request, pk=None):
        """
        Permanently delete this release and all its chart entries.
        This cannot be undone.
        """
        release = self.get_object()
        entry_count = MonthlyChartEntry.objects.filter(release=release).count()
        release_repr = str(release)
        release_id = release.pk
        chart_type = release.chart_type

        with transaction.atomic():
            MonthlyChartEntry.objects.filter(release=release).delete()
            PlatformChartEntry.objects.filter(release=release).delete()
            Certification.objects.filter(release=release).delete()
            release.delete()

        harmonize_chart_history(chart_type=chart_type)
        audit(request, 'hard_deleted_release', module='releases', new={
            'id': release_id, 'repr': release_repr, 'entries_deleted': entry_count,
        })
        bump_public_revision()
        return Response({'deleted': True, 'entries_deleted': entry_count}, status=200)


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
    queryset = MonthlyChart.objects.annotate(
        cms_entries_count=Count('entries', distinct=True),
        cms_combined_entries_count=Count(
            'entries', filter=Q(entries__platform__isnull=True), distinct=True
        ),
    ).order_by('-year', '-month')
    serializer_class = CmsMonthlyChartSerializer
    search_fields = ['label', 'chart_type', 'status', 'year']
    ordering_fields = ['year', 'month', 'chart_type', 'status', 'updated_at']
    module_name = 'charts'

    @staticmethod
    def _validate_for_publication(chart):
        """Validate only the public-facing Top 50 subset.

        The Combined scope is allowed to (and, for a full weekly-upload
        rebuild, normally does) hold more than 50 releases — everything that
        actually charted that month. Publish only requires that ranks 1-50
        exist and are consecutive; entries ranked below that are never
        deleted, they're simply outside what the public API serves.
        """
        combined = chart.entries.filter(platform__isnull=True)
        top_ranks = list(
            combined.filter(rank__range=(1, 50)).order_by('rank').values_list('rank', flat=True)
        )
        if not top_ranks:
            raise DRFValidationError({
                'entries': 'Add and review at least one Combined chart entry in the Top 50 before publishing.'
            })
        expected = list(range(1, len(top_ranks) + 1))
        if top_ranks != expected:
            raise DRFValidationError({
                'entries': 'Combined chart Top 50 ranks must be consecutive, starting at 1, with no gaps or duplicates. Use Re-rank before publishing.'
            })

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
        self._validate_for_publication(chart)
        chart.is_published = True
        chart.status = 'published'
        chart.published_by = request.user
        chart.published_at = timezone.now()
        chart.save(update_fields=['is_published', 'status', 'published_by', 'published_at', 'updated_at'])
        audit(request, 'published_chart', module='charts', obj=chart)
        return Response(CmsMonthlyChartSerializer(chart).data)

    @action(detail=False, methods=['get'])
    def options(self, request):
        rows = MonthlyChart.objects.order_by('-year', '-month').values(
            'id', 'year', 'month', 'label', 'chart_type', 'status',
            'is_published',
        )[:240]
        return Response(list(rows))

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        chart = self.get_object()
        chart.is_published = False
        chart.status = 'draft'
        chart.published_at = None
        chart.save(update_fields=['is_published', 'status', 'published_at', 'updated_at'])
        audit(request, 'unpublished_chart', module='charts', obj=chart)
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

    def perform_create(self, serializer):
        if (
            'total_points' in serializer.validated_data
            and 'raw_total_points' not in serializer.validated_data
        ):
            serializer.validated_data['raw_total_points'] = max(
                int(serializer.validated_data['total_points'] or 0),
                0,
            )
        obj = serializer.save()
        result = harmonize_chart_history(chart_type=obj.chart.chart_type)
        obj.refresh_from_db()
        audit(self.request, 'created', module=self.module_name, obj=obj, new={
            **serializer.data,
            'harmonization': result,
        })

    def perform_update(self, serializer):
        old = model_to_dict_safe(serializer.instance)
        # Rank is derived from points. Ignoring a directly supplied rank also
        # avoids transient unique-rank collisions; harmonization installs the
        # authoritative ordering immediately after the save.
        serializer.validated_data.pop('rank', None)
        if (
            'total_points' in serializer.validated_data
            and 'raw_total_points' not in serializer.validated_data
        ):
            serializer.validated_data['raw_total_points'] = max(
                int(serializer.validated_data['total_points'] or 0),
                0,
            )
        obj = serializer.save()
        result = harmonize_chart_history(chart_type=obj.chart.chart_type)
        obj.refresh_from_db()
        audit(self.request, 'updated', module=self.module_name, obj=obj, old=old, new={
            **serializer.data,
            'harmonization': result,
        })

    def perform_destroy(self, instance):
        chart_type = instance.chart.chart_type
        audit(self.request, 'deleted', module=self.module_name, obj=instance)
        instance.delete()
        harmonize_chart_history(chart_type=chart_type)

    @action(detail=False, methods=['post'])
    def harmonize(self, request):
        result = harmonize_chart_history(
            chart_type=request.data.get('chart_type'),
            chart_ids=request.data.get('chart_ids') or [],
        )
        audit(request, 'harmonized_chart_history', module=self.module_name, new=result)
        return Response(result)

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
        result = harmonize_chart_history(chart_ids=[chart.id])
        audit(request, 'reordered_entries', module=self.module_name, new={
            'chart_id': chart_id,
            **result,
        })
        return Response(result)


class CmsRegionalChartEntryViewSet(CmsBaseViewSet):
    """Read-only: RegionalChartEntry rows are entirely derived by
    sync_regional_chart_entries/harmonize_regional_chart_entries — a direct
    edit here would just be overwritten by the next harmonize run."""
    http_method_names = ['get', 'head', 'options']
    queryset = RegionalChartEntry.objects.select_related(
        'chart', 'release', 'release__artist'
    ).all()
    serializer_class = CmsRegionalChartEntrySerializer
    search_fields = ['release__title', 'release__artist__name', 'featured_artists']
    ordering_fields = ['rank', 'total_points', 'weeks_on_chart']
    module_name = 'chart_entries'

    def get_queryset(self):
        qs = super().get_queryset()
        chart_id = self.request.query_params.get('chart')
        region = self.request.query_params.get('region')
        if chart_id:
            qs = qs.filter(chart_id=chart_id)
        if region:
            qs = qs.filter(region=region)
        return qs.order_by('rank')



class CmsWeeklyUploadViewSet(CmsBaseViewSet):
    queryset = WeeklyUpload.objects.select_related('uploaded_by').all()
    serializer_class = CmsWeeklyUploadSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = ['chart_type', 'processing_notes']
    module_name = 'uploads'

    def perform_create(self, serializer):
        incoming_file = self.request.FILES.get('file')
        if not incoming_file:
            raise DRFValidationError({'file': 'Select an XLSX weekly chart workbook.'})
        original_filename = str(getattr(incoming_file, 'name', '') or 'weekly-chart.xlsx')
        # Raw chart workbooks are transient processing inputs. Saving them with
        # the global Cloudinary image backend makes valid XLSX ZIP containers
        # fail as "Unsupported ZIP file", so retain the filename and normalized
        # database rows instead of uploading the workbook as an image.
        upload = serializer.save(
            uploaded_by=self.request.user,
            file=original_filename,
        )
        try:
            result = process_weekly_upload(upload, file_obj=incoming_file)
        except Exception as exc:
            upload.processing_notes = f'Error: {exc}'
            upload.save(update_fields=['processing_notes'])
            raise DRFValidationError({'file': f'Could not process this workbook: {exc}'}) from exc
        upload.processing_notes = str(result)
        upload.save(update_fields=['processing_notes'])
        audit(
            self.request,
            'processed_weekly_chart',
            module='uploads',
            obj=upload,
            new=result,
        )

    @action(detail=False, methods=['post'])
    def rebuild_month(self, request):
        chart_type = request.data.get('chart_type', ChartType.SINGLES)
        year = int(request.data.get('year', timezone.now().year))
        month = int(request.data.get('month', timezone.now().month))
        result = rebuild_monthly_chart(chart_type, year, month)
        audit(
            request,
            'rebuilt_monthly_chart',
            module='uploads',
            new={'chart_type': chart_type, 'year': year, 'month': month, **result},
        )
        return Response(result)


class ChartUploadViewSet(CmsBaseViewSet):
    queryset = ChartUpload.objects.select_related('platform', 'uploaded_by', 'approved_by', 'published_by').all()
    serializer_class = ChartUploadSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = ['original_filename', 'status', 'chart_type', 'notes']
    module_name = 'chart_uploads'

    def perform_create(self, serializer):
        incoming_file = self.request.FILES.get('file')
        original_filename = getattr(incoming_file, 'name', '')
        # Parse workbook bytes directly. The global production storage handles
        # image media and must not receive XLSX/ZIP chart workbooks.
        upload = serializer.save(
            uploaded_by=self.request.user,
            original_filename=original_filename,
            file=None,
        )
        self._parse_and_validate(upload, file_obj=incoming_file)
        audit(self.request, 'uploaded_chart_file', module='uploads', obj=upload, new={'rows': upload.row_count, 'summary': upload.validation_summary})

    def _parse_and_validate(self, upload, file_obj=None):
        if file_obj:
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            rows = parse_chart_file(file_obj)
        elif upload.file:
            upload.file.open('rb')
            try:
                rows = parse_chart_file(upload.file)
            finally:
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

    def perform_create(self, serializer):
        super().perform_create(serializer)
        recalculate_certifications()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        recalculate_certifications()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        recalculate_certifications()


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

        # Artists — all name/identity/profile fields
        artist_qs = Artist.objects.exclude(status='archived').filter(
            Q(name__icontains=q) |
            Q(display_name__icontains=q) |
            Q(aliases__icontains=q) |
            Q(country__icontains=q) |
            Q(country_code__iexact=q) |
            Q(city_region__icontains=q) |
            Q(genre__icontains=q) |
            Q(biography__icontains=q) |
            Q(artist_type__icontains=q)
        )[:10]
        for a in artist_qs:
            parts = [p for p in [a.display_name, a.genre, a.country] if p]
            results.append({
                'type': 'artist', 'id': a.id,
                'title': a.name,
                'subtitle': ' · '.join(parts[:2]),
                'meta': a.country_code or '',
            })

        # Releases — title, canonical title, artist, featured artists, credits, ISRC, UPC, label, distributor
        release_qs = Release.objects.select_related('artist').exclude(status='archived').filter(
            Q(title__icontains=q) |
            Q(canonical_title__icontains=q) |
            Q(artist__name__icontains=q) |
            Q(artist__display_name__icontains=q) |
            Q(featured_artists__icontains=q) |
            Q(credited_artists__icontains=q) |
            Q(songwriters__icontains=q) |
            Q(producers__icontains=q) |
            Q(isrc__icontains=q) |
            Q(upc__icontains=q) |
            Q(label__icontains=q) |
            Q(distributor__icontains=q) |
            Q(country_code__icontains=q)
        )[:12]
        for r in release_qs:
            year_str = str(r.release_year) if r.release_year else ''
            meta_parts = [p for p in [r.isrc, r.upc, year_str] if p]
            results.append({
                'type': r.chart_type,
                'id': r.id,
                'title': r.title,
                'subtitle': r.artist.name,
                'meta': ' · '.join(meta_parts[:2]),
            })

        # News — title, headline, excerpt, body, category, tags, author
        news_qs = NewsArticle.objects.filter(
            Q(title__icontains=q) |
            Q(subheadline__icontains=q) |
            Q(excerpt__icontains=q) |
            Q(body__icontains=q) |
            Q(category__icontains=q) |
            Q(tags__icontains=q) |
            Q(author__icontains=q)
        )[:6]
        for article in news_qs:
            results.append({
                'type': 'news', 'id': article.id,
                'title': article.title,
                'subtitle': article.excerpt[:80] if article.excerpt else (article.category or ''),
                'meta': article.author or '',
            })

        # Certifications — release title, artist, level, notes
        cert_qs = Certification.objects.select_related('release', 'release__artist').filter(
            Q(release__title__icontains=q) |
            Q(release__artist__name__icontains=q) |
            Q(release__artist__display_name__icontains=q) |
            Q(level__icontains=q) |
            Q(notes__icontains=q)
        )[:6]
        for cert in cert_qs:
            results.append({
                'type': 'certification', 'id': cert.id,
                'title': cert.release.title,
                'subtitle': f'{cert.release.artist.name} · {cert.level.title()}',
                'meta': f'{int(cert.total_points or 0):,} pts · {cert.release.chart_type}',
            })

        return Response({'results': results})


def duplicate_artist_groups(limit=100):
    import unicodedata, re as _re
    artists = list(Artist.objects.exclude(status='archived').only(
        'id', 'name', 'display_name', 'country', 'country_code', 'aliases'
    ))
    release_counts = {
        row['artist_id']: row['cnt']
        for row in Release.objects.exclude(status='archived')
            .values('artist_id').annotate(cnt=Count('id'))
    }

    def key(name):
        s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode('ascii')
        return _re.sub(r'[^a-z0-9]+', '', s.lower())

    # Primary bucket: normalized name
    buckets = {}
    for artist in artists:
        k = key(artist.name)
        if k:
            buckets.setdefault(k, []).append(artist)

    # Secondary: if any artist's name appears as an alias of another, merge their buckets
    alias_to_key = {}
    for artist in artists:
        for alias in (artist.aliases or []):
            ak = key(alias)
            if ak:
                alias_to_key[ak] = key(artist.name)

    merged_buckets = {}
    for k, members in buckets.items():
        canonical = alias_to_key.get(k, k)
        merged_buckets.setdefault(canonical, set()).update(a.id for a in members)

    # Resolve sets back to artist objects
    id_to_artist = {a.id: a for a in artists}
    groups = []
    seen_ids = set()
    for member_ids in merged_buckets.values():
        unseen = [aid for aid in member_ids if aid not in seen_ids]
        if len(unseen) < 2:
            continue
        group_artists = [id_to_artist[aid] for aid in unseen if aid in id_to_artist]
        if len(group_artists) < 2:
            continue
        seen_ids.update(unseen)
        groups.append(sorted([
            {
                'id': a.id,
                'name': a.name,
                'display_name': a.display_name or a.name,
                'country': a.country,
                'country_code': a.country_code,
                'release_count': release_counts.get(a.id, 0),
            }
            for a in group_artists
        ], key=lambda x: (-x['release_count'], x['id'])))

    groups.sort(key=lambda g: (-len(g), -g[0]['release_count']))
    return groups[:limit]


def normalize_artist_key(name):
    import unicodedata, re
    value = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^a-z0-9]+', '', value.lower())
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
