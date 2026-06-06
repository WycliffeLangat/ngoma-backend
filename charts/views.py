from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticatedOrReadOnly
from django.db.models import Sum, Min, Count, Avg
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import *
from .pipeline import process_weekly_upload, rebuild_monthly_chart


class PlatformViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Platform.objects.filter(active=True)
    serializer_class = PlatformSerializer


class ArtistViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Artist.objects.all()
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
        entries = MonthlyChartEntry.objects.filter(
            release__artist=artist,
            release__chart_type=chart_type,
            platform__isnull=True
        ).select_related('chart', 'release').order_by('chart__year', 'chart__month', 'rank')

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
        entries = MonthlyChartEntry.objects.filter(
            release__artist=artist, release__chart_type=chart_type, platform__isnull=True
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
    queryset = Release.objects.select_related('artist').all()
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
            release=release
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
    queryset = MonthlyChart.objects.filter(is_published=True)
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
            chart_type=chart_type, is_published=True
        ).order_by('-year', '-month').first()
        if not chart:
            return Response({'error': 'No charts found'}, status=404)
        platform_id = request.query_params.get('platform', 'combined')
        serializer = self.get_serializer(chart, context={'request': request, 'platform_id': platform_id})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def year_end(self, request):
        """Year-end chart: aggregate all months in a given year."""
        year = int(request.query_params.get('year', 2024))
        chart_type = request.query_params.get('chart_type', 'singles')
        entries = MonthlyChartEntry.objects.filter(
            chart__year=year, chart__chart_type=chart_type, platform__isnull=True
        ).values('release__title', 'release__artist__name', 'release_id').annotate(
            total_pts=Sum('total_points'),
            months=Count('chart', distinct=True),
            best_rank=Min('rank')
        ).order_by('-total_pts')

        data = [{'rank': i+1, 'title': e['release__title'], 'artist': e['release__artist__name'],
                 'total_points': e['total_pts'], 'months_on_chart': e['months'],
                 'best_rank': e['best_rank']} for i, e in enumerate(entries)]
        return Response({'year': year, 'chart_type': chart_type, 'entries': data})

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """Comprehensive analytics data."""
        chart_type = request.query_params.get('chart_type', 'singles')
        year = int(request.query_params.get('year', 2024))
        month = request.query_params.get('month')

        charts = MonthlyChart.objects.filter(chart_type=chart_type, year=year)
        if month:
            charts = charts.filter(month=int(month))

        result = {}
        for chart in charts:
            entries = MonthlyChartEntry.objects.filter(chart=chart, platform__isnull=True)
            plat_entries = MonthlyChartEntry.objects.filter(chart=chart, platform__isnull=False)
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
        year = int(request.data.get('year', 2024))
        month = int(request.data.get('month', 10))
        result = rebuild_monthly_chart(chart_type, year, month)
        return Response(result)


class NewsArticleViewSet(viewsets.ModelViewSet):
    queryset = NewsArticle.objects.filter(is_published=True)
    serializer_class = NewsArticleSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return super().get_permissions()


class CertificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Certification.objects.select_related('release', 'release__artist')
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
