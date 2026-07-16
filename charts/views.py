from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticatedOrReadOnly
from django.db.models import Sum, Min, Count, Avg, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import *
from .serializers import *
from .artist_credits import release_credit_payload
from .pipeline import process_weekly_upload, rebuild_monthly_chart
from .cms_utils import published_artist_entries, published_top50_entries


class PlatformViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Platform.objects.filter(active=True)
    serializer_class = PlatformSerializer


class ArtistViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Artist.objects.exclude(status__in=['archived', 'inactive', 'rejected', 'draft'])
    serializer_class = ArtistSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        chart_type = self.request.query_params.get('chart_type')
        if chart_type:
            qs = qs.filter(releases__chart_type=chart_type).distinct()
        return qs

    @action(detail=True, methods=['get'])
    def chart_history(self, request, pk=None):
        artist = self.get_object()
        chart_type = request.query_params.get('chart_type', 'singles')
        entries = published_artist_entries(artist).filter(
            release__chart_type=chart_type,
        ).select_related('chart', 'release').order_by(
            'chart__year', 'chart__month', 'rank'
        )

        data = [{
            'month': e.chart.label,
            'title': e.release.title,
            'rank': e.rank,
            'points': e.total_points,
            'weeks': e.weeks_on_chart,
            'platforms': e.platform_count,
            'movement': e.movement,
        } for e in entries]
        return Response(data)

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        artist = self.get_object()
        chart_type = request.query_params.get('chart_type', 'singles')
        entries = published_artist_entries(artist).filter(
            release__chart_type=chart_type,
        )
        agg = entries.aggregate(
            total_pts=Sum('total_points'), peak=Min('rank'),
            months=Count('chart', distinct=True)
        )
        return Response({
            'name': artist.name,
            'chart_type': chart_type,
            'total_points': agg['total_pts'] or 0,
            'peak_rank': agg['peak'],
            'months_on_chart': agg['months'],
            'releases': entries.values('release__title').distinct().count(),
        })


class ReleaseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Release.objects.select_related('artist').exclude(
        status__in=['archived', 'inactive', 'rejected', 'draft']
    ).exclude(artist__status__in=['archived', 'inactive', 'rejected', 'draft'])
    serializer_class = ReleaseSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        chart_type = self.request.query_params.get('chart_type')
        artist_id = self.request.query_params.get('artist')
        if chart_type:
            qs = qs.filter(chart_type=chart_type)
        if artist_id:
            qs = qs.filter(artist_id=artist_id)
        return qs

    @action(detail=True, methods=['get'])
    def journey(self, request, pk=None):
        """Full chart journey for a release across all months and platforms."""
        release = self.get_object()
        entries = MonthlyChartEntry.objects.filter(
            release=release,
            chart__is_published=True,
            chart__status='published',
            rank__range=(1, 50),
        ).select_related('chart', 'platform').order_by('chart__year', 'chart__month', 'rank')

        data = []
        for e in entries:
            data.append({
                'month': e.chart.label,
                'year': e.chart.year,
                'month_num': e.chart.month,
                'platform': e.platform.name if e.platform else 'Combined',
                'rank': e.rank,
                'points': e.total_points,
                'weeks': e.weeks_on_chart,
                'prev_rank': e.prev_rank,
                'movement': e.movement,
                'peak_rank': e.peak_rank,
            })
        return Response({'release': ReleaseSerializer(release).data, 'journey': data})


class MonthlyChartViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MonthlyChart.objects.filter(is_published=True, status='published')
    serializer_class = MonthlyChartSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        chart_type = self.request.query_params.get('chart_type')
        if chart_type:
            qs = qs.filter(chart_type=chart_type)
        return qs

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        platform_id = request.query_params.get('platform', 'combined')
        serializer = self.get_serializer(instance, context={
            'request': request,
            'platform_id': platform_id
        })
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def latest(self, request):
        chart_type = request.query_params.get('chart_type', 'singles')
        chart = MonthlyChart.objects.filter(
            chart_type=chart_type, is_published=True, status='published'
        ).order_by('-year', '-month').first()
        if not chart:
            return Response({'error': 'No charts found'}, status=404)
        platform_id = request.query_params.get('platform', 'combined')
        serializer = self.get_serializer(chart, context={'request': request, 'platform_id': platform_id})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def year_end(self, request):
        """Year-end chart: aggregate all months in a given year."""
        chart_type = request.query_params.get('chart_type', 'singles')
        latest_chart = MonthlyChart.objects.filter(
            chart_type=chart_type, is_published=True, status='published'
        ).order_by('-year', '-month').first()
        default_year = latest_chart.year if latest_chart else timezone.now().year
        year = int(request.query_params.get('year', default_year))
        entries = published_top50_entries().filter(
            chart__year=year,
            chart__chart_type=chart_type,
        ).values('release__title', 'release_id').annotate(
            total_pts=Sum('total_points'),
            months=Count('chart', distinct=True),
            best_rank=Min('rank')
        ).order_by('-total_pts')

        entry_rows = list(entries)
        releases = {
            release.id: release
            for release in Release.objects.filter(
                id__in=[entry['release_id'] for entry in entry_rows]
            ).select_related('artist').prefetch_related('artist_credits__artist')
        }
        data = [{
            'rank': index + 1,
            'title': entry['release__title'],
            'artist': release_credit_payload(
                releases[entry['release_id']]
            )['artist_credit'],
            'total_points': entry['total_pts'],
            'months_on_chart': entry['months'],
            'best_rank': entry['best_rank'],
        } for index, entry in enumerate(entry_rows)]
        return Response({'year': year, 'chart_type': chart_type, 'entries': data})

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """Comprehensive analytics data."""
        chart_type = request.query_params.get('chart_type', 'singles')
        latest_chart = MonthlyChart.objects.filter(
            chart_type=chart_type, is_published=True, status='published'
        ).order_by('-year', '-month').first()
        default_year = latest_chart.year if latest_chart else timezone.now().year
        year = int(request.query_params.get('year', default_year))
        month = request.query_params.get('month')

        charts = MonthlyChart.objects.filter(
            chart_type=chart_type, year=year, is_published=True, status='published'
        )
        if month:
            charts = charts.filter(month=int(month))

        result = {}
        for chart in charts:
            entries = MonthlyChartEntry.objects.filter(chart=chart, platform__isnull=True, rank__range=(1, 50))
            plat_entries = MonthlyChartEntry.objects.filter(chart=chart, platform__isnull=False, rank__range=(1, 50))
            result[chart.label] = {
                'total_songs': entries.count(),
                'new_entries': entries.filter(prev_rank__isnull=True).count(),
                'returning': entries.filter(prev_rank__isnull=False).count(),
                'all_platform': entries.filter(platform_count=6 if chart_type == 'singles' else 2).count(),
                'top10': MonthlyChartEntrySerializer(entries.order_by('rank')[:10], many=True).data,
                'platform_ones': {
                    pe.platform.name: {'title': pe.release.title, 'artist': pe.release.artist.name}
                    for pe in plat_entries.filter(rank=1).select_related('platform', 'release', 'release__artist')
                },
                'coverage_dist': {
                    str(i)+'/'+str(6 if chart_type=='singles' else 2):
                    entries.filter(platform_count=i).count()
                    for i in range(1, (7 if chart_type=='singles' else 3))
                },
                'biggest_riser': MonthlyChartEntrySerializer(
                    entries.filter(prev_rank__isnull=False).order_by('rank').first()
                ).data if entries.filter(prev_rank__isnull=False).exists() else None,
            }
        return Response(result)


class WeeklyUploadViewSet(viewsets.ModelViewSet):
    queryset = WeeklyUpload.objects.all()
    serializer_class = WeeklyUploadSerializer
    permission_classes = [IsAdminUser]

    def perform_create(self, serializer):
        upload = serializer.save(uploaded_by=self.request.user)
        try:
            result = process_weekly_upload(upload)
            upload.processing_notes = str(result)
            upload.save()
        except Exception as e:
            upload.processing_notes = f"Error: {str(e)}"
            upload.save()

    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        upload = self.get_object()
        try:
            result = process_weekly_upload(upload)
            return Response({'status': 'reprocessed', 'result': result})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'])
    def rebuild_month(self, request):
        chart_type = request.data.get('chart_type', 'singles')
        latest_chart = MonthlyChart.objects.filter(chart_type=chart_type).order_by('-year', '-month').first()
        today = timezone.now()
        default_year = latest_chart.year if latest_chart else today.year
        default_month = latest_chart.month if latest_chart else today.month
        year = int(request.data.get('year', default_year))
        month = int(request.data.get('month', default_month))
        result = rebuild_monthly_chart(chart_type, year, month)
        return Response(result)


class NewsArticleViewSet(viewsets.ModelViewSet):
    queryset = NewsArticle.objects.filter(
        is_published=True,
        status='published',
    ).filter(Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=timezone.now())).select_related(
        'related_artist', 'related_release', 'related_release__artist'
    ).prefetch_related('related_release__artist_credits__artist').order_by(
        '-pinned', '-featured', '-published_at'
    )
    serializer_class = NewsArticleSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['news_artists'] = list(
            Artist.objects.exclude(image='')
            .exclude(status__in=['archived', 'inactive', 'rejected', 'draft'])
            .only('id', 'name', 'display_name', 'aliases', 'image')
        )
        context['news_releases'] = list(
            Release.objects.exclude(cover_image='')
            .exclude(status__in=['archived', 'inactive', 'rejected', 'draft'])
            .select_related('artist')
            .prefetch_related('artist_credits__artist')
            .only('id', 'title', 'cover_image', 'artist_id')
        )
        return context


class CertificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Certification.objects.select_related('release', 'release__artist').filter(
        is_hidden=False
    ).exclude(
        release__status__in=['archived', 'inactive', 'rejected', 'draft']
    ).exclude(release__artist__status__in=['archived', 'inactive', 'rejected', 'draft'])
    serializer_class = CertificationSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        level = self.request.query_params.get('level')
        chart_type = self.request.query_params.get('chart_type')
        if level:
            qs = qs.filter(level=level)
        if chart_type:
            qs = qs.filter(release__chart_type=chart_type)
        return qs


class NormalizationRuleViewSet(viewsets.ModelViewSet):
    queryset = NormalizationRule.objects.all()
    serializer_class = NormalizationRuleSerializer
    permission_classes = [IsAdminUser]
