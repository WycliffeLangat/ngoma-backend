from collections import defaultdict

from django.db.models import Prefetch
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AuditLog,
    Artist,
    Certification,
    CertificationRule,
    Country,
    MethodologySetting,
    MonthlyChart,
    MonthlyChartEntry,
    NewsArticle,
    PageContent,
    Platform,
    Release,
    SiteSetting,
)


HIDDEN_STATUSES = {"archived", "inactive", "rejected", "draft"}

# Every CMS module that can alter something rendered by the public app.  Audit
# rows give us one generic revision signal, including bulk/custom CMS actions
# that update several models at once.
PUBLIC_DATA_AUDIT_MODULES = {
    "artists",
    "releases",
    "countries",
    "platforms",
    "charts",
    "chart_entries",
    "chart_uploads",
    "uploads",
    "news",
    "media",
    "settings",
    "page_content",
    "certifications",
    "certification_rules",
    "methodology",
}


def _public_data_revision():
    latest = (
        AuditLog.objects.filter(module__in=PUBLIC_DATA_AUDIT_MODULES)
        .values("id", "created_at")
        .first()
    )
    if not latest:
        return "0"
    return f"{latest['id']}:{latest['created_at'].isoformat()}"


def _disable_response_cache(response):
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def _file_url(request, field):
    if not field:
        return ""
    try:
        return request.build_absolute_uri(field.url)
    except (ValueError, AttributeError):
        return ""


def _is_public_status(value):
    return (value or "active").lower() not in HIDDEN_STATUSES


def _compact(payload):
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != [] and value != {}
    }


def _release_payload(request, release):
    artist = release.artist
    # Use artist country as the authoritative source for display country on releases.
    display_country = artist.country or release.country
    display_country_code = artist.country_code or release.country_code
    return _compact({
        "id": release.id,
        "title": release.title,
        "chart_type": release.chart_type,
        "artist_id": release.artist_id,
        "artist_slug": artist.slug,
        "artist": artist.display_name or artist.name,
        "flag": artist.flag,
        "featured_artists": release.featured_artists,
        "credited_artists": release.credited_artists,
        "songwriters": release.songwriters,
        "producers": release.producers,
        "release_year": release.release_year,
        "release_date": release.release_date,
        "isrc": release.isrc,
        "upc": release.upc,
        "number_of_tracks": release.number_of_tracks,
        "country": display_country,
        "country_code": display_country_code,
        "genre": release.genre,
        "label": release.label,
        "distributor": release.distributor,
        "cover_image": _file_url(request, release.cover_image),
        "spotify_url": release.spotify_url,
        "apple_music_url": release.apple_music_url,
        "boomplay_url": release.boomplay_url,
        "audiomack_url": release.audiomack_url,
        "youtube_url": release.youtube_url,
        "tiktok_url": release.tiktok_url,
        "shazam_url": release.shazam_url,
        "radio_info": release.radio_info,
        "status": release.status,
        "updated_at": release.updated_at,
    })


def _entry_payload(request, entry):
    release = entry.release
    artist = release.artist
    artist_name = artist.display_name or artist.name
    featured_artists = release.featured_artists or entry.featured_artists
    # Artist country is authoritative — release.country may be stale if set from
    # a previous artist country at import time and the artist was later updated.
    display_country = artist.country or release.country
    display_country_code = artist.country_code or release.country_code

    return {
        "id": entry.id,
        "release_id": release.id,
        "artist_id": artist.id,
        "r": entry.rank,
        "t": release.title,
        "a": artist_name,
        "pa": artist_name,
        "fa": featured_artists,
        "p": entry.total_points,
        "rp": entry.raw_total_points,
        "pl": f"{entry.platform_count}/{entry.platform_max}" if entry.platform_count else "",
        "w": entry.weeks_on_chart,
        "y": release.release_year or entry.release_year,
        "c": entry.confidence,
        "co": display_country,
        "cc": display_country_code,
        "fl": artist.flag,
        # Include the editable release fields on every chart row.  The public
        # app can therefore render a CMS edit immediately without having to
        # join against the bundled/static release dataset.
        "genre": release.genre,
        "label": release.label,
        "distributor": release.distributor,
        "release_date": release.release_date,
        "isrc": release.isrc,
        "upc": release.upc,
        "number_of_tracks": release.number_of_tracks,
        "songwriters": release.songwriters,
        "producers": release.producers,
        "cover_image": _file_url(request, release.cover_image),
        "spotify_url": release.spotify_url,
        "apple_music_url": release.apple_music_url,
        "boomplay_url": release.boomplay_url,
        "audiomack_url": release.audiomack_url,
        "youtube_url": release.youtube_url,
        "tiktok_url": release.tiktok_url,
        "shazam_url": release.shazam_url,
        "radio_info": release.radio_info,
    }


def _chart_data(request, charts):
    full = {
        "singles": {"combined": {}, "platforms": {}},
        "albums": {"combined": {}, "platforms": {}},
    }
    months = []

    for chart in charts:
        if chart.label not in months:
            months.append(chart.label)
        chart_bucket = full.setdefault(chart.chart_type, {"combined": {}, "platforms": {}})
        for entry in chart.public_entries:
            if not _is_public_status(entry.release.status) or not _is_public_status(entry.release.artist.status):
                continue
            row = _entry_payload(request, entry)
            if entry.platform_id is None:
                chart_bucket["combined"].setdefault(chart.label, []).append(row)
            elif entry.platform.active:
                platform_key = entry.platform.name.upper()
                platform_bucket = chart_bucket["platforms"].setdefault(platform_key, {})
                platform_bucket.setdefault(chart.label, []).append(row)

    return months, full


@method_decorator(never_cache, name="dispatch")
class PublicAppDataView(APIView):
    """One uncached source of truth used to hydrate the complete public app."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        public_entries = MonthlyChartEntry.objects.select_related(
            "release", "release__artist", "platform"
        ).order_by("rank")
        charts = list(
            MonthlyChart.objects.filter(is_published=True, status="published")
            .prefetch_related(Prefetch("entries", queryset=public_entries, to_attr="public_entries"))
            .order_by("year", "month", "chart_type")
        )
        months, full = _chart_data(request, charts)

        public_release_ids = {
            entry.release_id
            for chart in charts
            for entry in chart.public_entries
            if _is_public_status(entry.release.status)
            and _is_public_status(entry.release.artist.status)
        }
        public_artist_ids = {
            entry.release.artist_id
            for chart in charts
            for entry in chart.public_entries
            if entry.release_id in public_release_ids
        }

        artists = [
            _compact({
                "id": artist.id,
                "name": artist.name,
                "slug": artist.slug,
                "display_name": artist.display_name,
                "public_name": artist.display_name or artist.name,
                "aliases": artist.aliases,
                "country": artist.country,
                "country_code": artist.country_code,
                "flag": artist.flag,
                "city_region": artist.city_region,
                "genre": artist.genre,
                "biography": artist.biography,
                "image": _file_url(request, artist.image),
                "artist_type": artist.artist_type,
                "verified": artist.verified,
                "status": artist.status,
                "social_links": _compact({
                    "spotify": artist.spotify_url,
                    "apple_music": artist.apple_music_url,
                    "youtube": artist.youtube_url,
                    "boomplay": artist.boomplay_url,
                    "audiomack": artist.audiomack_url,
                    "tiktok": artist.tiktok_url,
                    "instagram": artist.instagram_url,
                    "x": artist.x_url,
                    "facebook": artist.facebook_url,
                    "website": artist.website_url,
                }),
                "updated_at": artist.updated_at,
            })
            for artist in Artist.objects.filter(id__in=public_artist_ids)
            if _is_public_status(artist.status)
        ]
        releases = [
            _release_payload(request, release)
            for release in Release.objects.select_related("artist").filter(id__in=public_release_ids)
            if _is_public_status(release.status) and _is_public_status(release.artist.status)
        ]
        platforms = list(
            Platform.objects.filter(active=True).values(
                "id", "name", "slug", "short_name", "color", "brand_color",
                "chart_size", "max_chart_size", "points_base", "points_method",
                "supports_singles", "supports_albums", "display_order", "active",
            )
        )
        countries = list(
            Country.objects.filter(active=True).values(
                "id", "name", "code", "region", "flag", "display_order", "active"
            )
        )
        settings = {item.key: item.value for item in SiteSetting.objects.all()}
        page_content = defaultdict(list)
        for item in PageContent.objects.filter(is_visible=True):
            page_content[item.page].append(
                {
                    "id": item.id,
                    "section": item.section,
                    "title": item.title,
                    "content": item.content,
                    "data": item.data,
                    "display_order": item.display_order,
                    "updated_at": item.updated_at,
                }
            )

        news = NewsArticle.objects.filter(
            is_published=True,
            status="published",
        ).filter(scheduled_for__isnull=True) | NewsArticle.objects.filter(
            is_published=True,
            status="published",
            scheduled_for__lte=timezone.now(),
        )
        news = news.distinct().order_by("-pinned", "-featured", "-published_at")

        certifications = Certification.objects.select_related("release", "release__artist").filter(
            is_hidden=False
        )

        response = Response(
            {
                "revision": _public_data_revision(),
                "generated_at": timezone.now(),
                "months": months,
                "full": full,
                "artists": artists,
                "releases": releases,
                "platforms": platforms,
                "countries": countries,
                "settings": settings,
                "page_content": dict(page_content),
                "news": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "slug": item.slug,
                        "category": item.category,
                        "excerpt": item.excerpt,
                        "subheadline": item.subheadline,
                        "body": item.body,
                        "emoji": item.emoji,
                        "cover_image": _file_url(request, item.cover_image),
                        "gallery": item.gallery,
                        "tags": item.tags,
                        "author": item.author,
                        "source_links": item.source_links,
                        "seo_title": item.seo_title,
                        "seo_description": item.seo_description,
                        "featured": item.featured,
                        "pinned": item.pinned,
                        "breaking": item.breaking,
                        "published_at": item.published_at,
                        "updated_at": item.updated_at,
                        "related_release": item.related_release_id,
                        "related_artist": item.related_artist_id,
                    }
                    for item in news
                ],
                "certifications": [
                    {
                        "id": item.id,
                        "release_id": item.release_id,
                        "title": item.release.title,
                        "artist": item.release.artist.display_name or item.release.artist.name,
                        "country": item.release.artist.country or item.release.country,
                        "country_code": item.release.artist.country_code or item.release.country_code,
                        "chart_type": item.release.chart_type,
                        "level": item.level,
                        "total_points": item.total_points,
                        "is_official": item.is_official,
                        "certification_date": item.certification_date,
                        "certified_at": item.certified_at,
                        "previous_level": item.previous_level,
                        "notes": item.notes,
                    }
                    for item in certifications
                    if _is_public_status(item.release.status)
                    and _is_public_status(item.release.artist.status)
                ],
                "certification_rules": list(
                    CertificationRule.objects.filter(active=True).values(
                        "level", "threshold", "active", "updated_at"
                    )
                ),
                "methodology": list(
                    MethodologySetting.objects.filter(is_active=True).values(
                        "id", "version", "name", "config", "is_active", "created_at"
                    )
                ),
            }
        )
        return _disable_response_cache(response)


@method_decorator(never_cache, name="dispatch")
class PublicAppRevisionView(APIView):
    """Lightweight change signal used by an open public app to detect CMS saves."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return _disable_response_cache(Response({"revision": _public_data_revision()}))
