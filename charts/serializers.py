from rest_framework import serializers
from .models import *


class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = ['id', 'name', 'slug', 'color', 'chart_size', 'points_base']


class ArtistSerializer(serializers.ModelSerializer):
    total_points = serializers.SerializerMethodField()
    peak_rank = serializers.SerializerMethodField()
    months_on_chart = serializers.SerializerMethodField()
    flag = serializers.ReadOnlyField()

    class Meta:
        model = Artist
        fields = ['id', 'name', 'slug', 'country', 'country_code', 'flag',
                  'total_points', 'peak_rank', 'months_on_chart']

    def get_total_points(self, obj):
        from django.db.models import Sum
        return MonthlyChartEntry.objects.filter(
            release__artist=obj, platform__isnull=True
        ).aggregate(t=Sum('total_points'))['t'] or 0

    def get_peak_rank(self, obj):
        from django.db.models import Min
        result = MonthlyChartEntry.objects.filter(
            release__artist=obj, platform__isnull=True
        ).aggregate(p=Min('rank'))['p']
        return result

    def get_months_on_chart(self, obj):
        return MonthlyChartEntry.objects.filter(
            release__artist=obj, platform__isnull=True
        ).values('chart').distinct().count()


class ReleaseSerializer(serializers.ModelSerializer):
    artist_name = serializers.CharField(source='artist.name')
    country = serializers.CharField(source='artist.country')
    country_code = serializers.CharField(source='artist.country_code')
    flag = serializers.ReadOnlyField(source='artist.flag')
    certifications = serializers.SerializerMethodField()

    class Meta:
        model = Release
        fields = ['id', 'title', 'artist_name', 'country', 'country_code',
                  'flag', 'chart_type', 'certifications']

    def get_certifications(self, obj):
        return list(obj.certifications.values_list('level', flat=True))


class MonthlyChartEntrySerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='release.title')
    artist = serializers.CharField(source='release.artist.name')
    artist_id = serializers.IntegerField(source='release.artist.id')
    country = serializers.CharField(source='release.artist.country')
    country_code = serializers.CharField(source='release.artist.country_code')
    flag = serializers.ReadOnlyField(source='release.artist.flag')
    release_id = serializers.IntegerField(source='release.id')
    platform_name = serializers.SerializerMethodField()
    movement = serializers.ReadOnlyField()
    certifications = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyChartEntry
        fields = [
            'rank', 'title', 'artist', 'artist_id', 'country', 'country_code',
            'flag', 'release_id', 'total_points', 'weeks_on_chart',
            'platform_count', 'peak_rank', 'prev_rank', 'movement',
            'platform_name', 'certifications'
        ]

    def get_platform_name(self, obj):
        return obj.platform.name if obj.platform else 'Combined'

    def get_certifications(self, obj):
        return list(obj.release.certifications.values_list('level', flat=True))


class MonthlyChartSerializer(serializers.ModelSerializer):
    entries = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyChart
        fields = ['id', 'year', 'month', 'label', 'chart_type', 'is_published', 'entries']

    def get_entries(self, obj):
        platform_id = self.context.get('platform_id')
        qs = obj.entries.select_related('release', 'release__artist', 'platform')
        if platform_id == 'combined':
            qs = qs.filter(platform__isnull=True)
        elif platform_id:
            qs = qs.filter(platform_id=platform_id)
        return MonthlyChartEntrySerializer(qs.order_by('rank'), many=True).data


class NewsArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsArticle
        fields = ['id', 'title', 'slug', 'category', 'excerpt', 'body', 'emoji',
                  'published_at', 'related_release', 'related_artist']


class WeeklyUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklyUpload
        fields = ['id', 'chart_type', 'year', 'month', 'week', 'file',
                  'processed', 'processing_notes', 'duplicates_dropped',
                  'entries_processed', 'uploaded_at']
        read_only_fields = ['processed', 'processing_notes', 'duplicates_dropped',
                            'entries_processed', 'uploaded_at']


class CertificationSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='release.title')
    artist = serializers.CharField(source='release.artist.name')
    country = serializers.CharField(source='release.artist.country')
    country_code = serializers.CharField(source='release.artist.country_code')
    flag = serializers.ReadOnlyField(source='release.artist.flag')
    chart_type = serializers.CharField(source='release.chart_type')

    class Meta:
        model = Certification
        fields = ['id', 'title', 'artist', 'country', 'country_code', 'flag',
                  'chart_type', 'level', 'total_points', 'certified_at']


class NormalizationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NormalizationRule
        fields = '__all__'
