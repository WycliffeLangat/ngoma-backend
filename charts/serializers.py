from rest_framework import serializers
from .models import *
from .artist_credits import release_credit_payload


def artist_credit_summary(artist):
    return {
        'id': artist.id,
        'name': artist.name,
        'display_name': artist.display_name,
        'public_name': artist.display_name or artist.name,
        'slug': artist.slug,
        'country': artist.country,
        'country_code': artist.country_code,
    }


class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = [
            'id', 'name', 'slug', 'short_name', 'logo', 'color', 'brand_color',
            'chart_size', 'max_chart_size', 'points_base', 'points_method',
            'supports_singles', 'supports_albums', 'display_order', 'active',
        ]


class ArtistSerializer(serializers.ModelSerializer):
    total_points = serializers.SerializerMethodField()
    peak_rank = serializers.SerializerMethodField()
    months_on_chart = serializers.SerializerMethodField()
    flag = serializers.ReadOnlyField()

    class Meta:
        model = Artist
        fields = [
            'id', 'name', 'display_name', 'slug', 'aliases', 'country',
            'country_code', 'flag', 'city_region', 'genre', 'biography', 'image',
            'spotify_url', 'apple_music_url', 'youtube_url', 'boomplay_url',
            'audiomack_url', 'tiktok_url', 'instagram_url', 'x_url',
            'facebook_url', 'website_url', 'artist_type', 'status', 'verified',
            'updated_at', 'total_points', 'peak_rank', 'months_on_chart',
        ]

    def get_total_points(self, obj):
        from django.db.models import Sum
        from .cms_utils import published_artist_entries
        return published_artist_entries(obj).aggregate(t=Sum('total_points'))['t'] or 0

    def get_peak_rank(self, obj):
        from django.db.models import Min
        from .cms_utils import published_artist_entries
        result = published_artist_entries(obj).aggregate(p=Min('rank'))['p']
        return result

    def get_months_on_chart(self, obj):
        from .cms_utils import published_artist_entries
        return published_artist_entries(obj).values('chart').distinct().count()


class ReleaseSerializer(serializers.ModelSerializer):
    artist_name = serializers.SerializerMethodField()
    artist_country = serializers.CharField(source='artist.country')
    artist_country_code = serializers.CharField(source='artist.country_code')
    flag = serializers.ReadOnlyField(source='artist.flag')
    certifications = serializers.SerializerMethodField()
    artist_credit = serializers.SerializerMethodField()
    primary_artists = serializers.SerializerMethodField()
    featured_artist_profiles = serializers.SerializerMethodField()

    class Meta:
        model = Release
        fields = [
            'id', 'title', 'artist', 'artist_name', 'artist_country',
            'artist_country_code', 'flag', 'chart_type', 'featured_artists',
            'credited_artists', 'songwriters', 'producers', 'release_year',
            'release_date', 'isrc', 'upc', 'number_of_tracks', 'country',
            'country_code', 'genre', 'label', 'distributor', 'cover_image',
            'spotify_url', 'apple_music_url', 'boomplay_url', 'audiomack_url',
            'youtube_url', 'tiktok_url', 'shazam_url', 'radio_info', 'status',
            'updated_at', 'certifications', 'artist_credit', 'primary_artists',
            'featured_artist_profiles',
        ]

    def get_artist_name(self, obj):
        return obj.artist.display_name or obj.artist.name

    def get_certifications(self, obj):
        return list(obj.certifications.filter(is_hidden=False).values_list('level', flat=True))

    def get_artist_credit(self, obj):
        return release_credit_payload(obj)['artist_credit']

    def get_primary_artists(self, obj):
        return [artist_credit_summary(artist) for artist in release_credit_payload(obj)['primary_artists']]

    def get_featured_artist_profiles(self, obj):
        return [artist_credit_summary(artist) for artist in release_credit_payload(obj)['featured_artists']]


class MonthlyChartEntrySerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='release.title')
    artist = serializers.SerializerMethodField()
    artist_id = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    country_code = serializers.SerializerMethodField()
    flag = serializers.SerializerMethodField()
    release_id = serializers.IntegerField(source='release.id')
    platform_name = serializers.SerializerMethodField()
    movement = serializers.ReadOnlyField()
    certifications = serializers.SerializerMethodField()
    artist_credit = serializers.SerializerMethodField()
    primary_artists = serializers.SerializerMethodField()
    featured_artist_profiles = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyChartEntry
        fields = [
            'rank', 'title', 'artist', 'artist_id', 'country', 'country_code',
            'flag', 'release_id', 'total_points', 'raw_total_points',
            'weeks_on_chart', 'platform_count', 'platform_max',
            'peak_rank', 'prev_rank', 'movement',
            'platform_name', 'certifications', 'artist_credit',
            'primary_artists', 'featured_artist_profiles',
        ]

    def get_platform_name(self, obj):
        return obj.platform.name if obj.platform else 'Combined'

    def _lead_artist(self, obj):
        credits = release_credit_payload(obj.release, entry_featured=obj.featured_artists)
        return credits['primary_artists'][0] if credits['primary_artists'] else obj.release.artist

    def get_artist(self, obj):
        return release_credit_payload(
            obj.release,
            entry_featured=obj.featured_artists,
        )['primary_artist_credit']

    def get_artist_id(self, obj):
        return self._lead_artist(obj).id

    def get_country(self, obj):
        return self._lead_artist(obj).country

    def get_country_code(self, obj):
        return self._lead_artist(obj).country_code

    def get_flag(self, obj):
        return self._lead_artist(obj).flag

    def get_certifications(self, obj):
        return list(obj.release.certifications.filter(is_hidden=False).values_list('level', flat=True))

    def get_artist_credit(self, obj):
        return release_credit_payload(obj.release, entry_featured=obj.featured_artists)['artist_credit']

    def get_primary_artists(self, obj):
        return [artist_credit_summary(artist) for artist in release_credit_payload(obj.release)['primary_artists']]

    def get_featured_artist_profiles(self, obj):
        return [artist_credit_summary(artist) for artist in release_credit_payload(obj.release, entry_featured=obj.featured_artists)['featured_artists']]


class MonthlyChartSerializer(serializers.ModelSerializer):
    entries = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyChart
        fields = ['id', 'year', 'month', 'label', 'chart_type', 'is_published', 'entries']

    def get_entries(self, obj):
        platform_id = self.context.get('platform_id')
        qs = obj.entries.select_related('release', 'release__artist', 'platform').prefetch_related('release__artist_credits__artist').exclude(
            release__status__in=['archived', 'inactive', 'rejected', 'draft']
        ).exclude(release__artist__status__in=['archived', 'inactive', 'rejected', 'draft'])
        if platform_id == 'combined':
            qs = qs.filter(platform__isnull=True)
        elif platform_id:
            qs = qs.filter(platform_id=platform_id)
        return MonthlyChartEntrySerializer(
            qs.filter(rank__gte=1, rank__lte=50).order_by('rank'),
            many=True,
        ).data


class NewsArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsArticle
        fields = [
            'id', 'title', 'slug', 'category', 'excerpt', 'subheadline', 'body',
            'emoji', 'cover_image', 'gallery', 'tags', 'author', 'source_links',
            'seo_title', 'seo_description', 'featured', 'pinned', 'breaking',
            'published_at', 'updated_at', 'related_release', 'related_artist',
        ]


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
    artist = serializers.SerializerMethodField()
    country = serializers.CharField(source='release.artist.country')
    country_code = serializers.CharField(source='release.artist.country_code')
    flag = serializers.ReadOnlyField(source='release.artist.flag')
    chart_type = serializers.CharField(source='release.chart_type')

    class Meta:
        model = Certification
        fields = ['id', 'title', 'artist', 'country', 'country_code', 'flag',
                  'chart_type', 'level', 'total_points', 'is_official',
                  'certification_date', 'previous_level', 'notes', 'certified_at']

    def get_artist(self, obj):
        return release_credit_payload(obj.release)['artist_credit']


class NormalizationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NormalizationRule
        fields = '__all__'
