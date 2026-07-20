from collections import defaultdict
import hashlib

from django.core.cache import cache
from django.db.models import Max, Min, Prefetch, Q, Sum
from django.db.models.functions import Coalesce
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
    RegionalChartEntry,
    Release,
    SiteSetting,
)
from .artist_credits import release_credit_payload
from .cms_utils import published_artist_entries
from .methodology import HIDDEN_STATUSES, is_public_status, public_points
from .news_media import news_media_payload

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
    action_rev = (
        SiteSetting.objects.filter(key='_cms_action_revision')
        .values_list('value', flat=True)
        .first()
    )
    if action_rev and isinstance(action_rev, dict) and action_rev.get('ts'):
        return f"x:{action_rev.get('ts')}"

    latest_log = (
        AuditLog.objects.filter(module__in=PUBLIC_DATA_AUDIT_MODULES)
        .values("id", "created_at")
        .first()
    )

    # Pull the most-recently-touched timestamps directly from the data models.
    # This guarantees the revision changes on every CMS save even if the audit
    # log write fails silently (its body is wrapped in try/except).
    aggregates = {
        "artist": Artist.objects.aggregate(m=Max("updated_at"))["m"],
        "release": Release.objects.aggregate(m=Max("updated_at"))["m"],
        "chart": MonthlyChart.objects.aggregate(m=Max("updated_at"))["m"],
        "news": NewsArticle.objects.aggregate(m=Max("updated_at"))["m"],
        "certification": Certification.objects.aggregate(m=Max("certified_at"))["m"],
        "page_content": PageContent.objects.aggregate(m=Max("updated_at"))["m"],
        "setting": SiteSetting.objects.exclude(key__startswith="_").aggregate(m=Max("updated_at"))["m"],
    }
    latest_artist = aggregates["artist"]
    latest_release = aggregates["release"]
    latest_chart = aggregates["chart"]
    latest_news = aggregates["news"]
    latest_certification = aggregates["certification"]
    latest_page_content = aggregates["page_content"]
    latest_setting = aggregates["setting"]

    # Explicit bump written by merge/hard_delete actions - guarantees a revision
    # change even when audit() fails AND the deleted record wasn't the most
    # recently updated model (so Max("updated_at") stays the same).

    parts = []
    if latest_log:
        parts.append(f"log:{latest_log['id']}")
    if latest_artist:
        parts.append(f"a:{latest_artist.isoformat()}")
    if latest_release:
        parts.append(f"r:{latest_release.isoformat()}")
    if latest_chart:
        parts.append(f"c:{latest_chart.isoformat()}")
    if latest_news:
        parts.append(f"n:{latest_news.isoformat()}")
    if latest_certification:
        parts.append(f"cert:{latest_certification.isoformat()}")
    if latest_page_content:
        parts.append(f"pc:{latest_page_content.isoformat()}")
    if latest_setting:
        parts.append(f"s:{latest_setting.isoformat()}")
    if action_rev and isinstance(action_rev, dict):
        parts.append(f"x:{action_rev.get('ts', '')}")

    return "|".join(parts) if parts else "0"


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


_is_public_status = is_public_status


def _artist_payload(request, artist):
    return _compact({
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


def _compact(payload):
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != [] and value != {}
    }


def _release_payload(request, release):
    credits = release_credit_payload(release)
    artist = credits["primary_artists"][0] if credits["primary_artists"] else release.artist
    # Use artist country as the authoritative source for display country on releases.
    display_country = artist.country or release.country
    display_country_code = artist.country_code or release.country_code
    return _compact({
        "id": release.id,
        "title": release.title,
        "chart_type": release.chart_type,
        "artist_id": artist.id,
        "artist_slug": artist.slug,
        "artist": artist.display_name or artist.name,
        "artist_credit": credits["artist_credit"],
        "primary_artist_credit": credits["primary_artist_credit"],
        "featured_artist_credit": credits["featured_artist_credit"],
        "primary_artist_ids": [item.id for item in credits["primary_artists"]],
        "featured_artist_ids": [item.id for item in credits["featured_artists"]],
        "primary_artists": [_artist_payload(request, item) for item in credits["primary_artists"]],
        "featured_artist_profiles": [_artist_payload(request, item) for item in credits["featured_artists"]],
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


def _movement_value(prev_rank, rank, appeared_before):
    """Same semantics as MonthlyChartEntry.movement / RegionalChartEntry.movement,
    but takes appeared_before as a precomputed bool instead of running a query —
    callers here compute it in bulk from already-fetched data (see _chart_data)."""
    if prev_rank is None:
        return 're-entry' if appeared_before else 'new'
    d = prev_rank - rank
    if d > 0:
        return f'+{d}'
    if d < 0:
        return str(d)
    return '='


def _entry_payload(request, entry, movement=None):
    release = entry.release
    featured_artists = release.featured_artists or entry.featured_artists
    credits = release_credit_payload(release, entry_featured=featured_artists)
    artist = credits["primary_artists"][0] if credits["primary_artists"] else release.artist
    artist_name = artist.display_name or artist.name
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
        "a": credits["primary_artist_credit"] or artist_name,
        "pa": credits["primary_artist_credit"] or artist_name,
        "fa": featured_artists,
        "artist_credit": credits["artist_credit"],
        "primary_artist_credit": credits["primary_artist_credit"],
        "featured_artist_credit": credits["featured_artist_credit"],
        "primary_artist_ids": [item.id for item in credits["primary_artists"]],
        "featured_artist_ids": [item.id for item in credits["featured_artists"]],
        "primary_artists": [_artist_payload(request, item) for item in credits["primary_artists"]],
        "featured_artist_profiles": [_artist_payload(request, item) for item in credits["featured_artists"]],
        "credited_artists": release.credited_artists,
        "p": entry.total_points,
        "rp": entry.raw_total_points,
        "pl": f"{entry.platform_count}/{entry.platform_max}" if entry.platform_count else "",
        "w": entry.weeks_on_chart,
        "y": release.release_year or entry.release_year,
        "c": entry.confidence,
        "co": display_country,
        "cc": display_country_code,
        "fl": artist.flag,
        "prev_rank": entry.prev_rank,
        "last_month": entry.prev_rank if entry.prev_rank is not None else "—",
        "peak_rank": entry.peak_rank,
        "movement": entry.movement if movement is None else movement,
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


def _regional_artist_charts(request, charts):
    """Build independent regional artist charts from every regional release
    candidate, before either release chart is trimmed to its public Top 50."""
    aggregates = defaultdict(dict)
    period_order = {}

    for chart in charts:
        period_order[chart.label] = (chart.year, chart.month)
        for entry in chart.regional_candidate_entries:
            if not _is_public_status(entry.release.status) or not _is_public_status(entry.release.artist.status):
                continue
            credits = release_credit_payload(
                entry.release,
                entry_featured=entry.release.featured_artists or entry.featured_artists,
            )
            seen_artist_ids = set()
            for artist in credits["primary_artists"] + credits["featured_artists"]:
                if artist.id in seen_artist_ids:
                    continue
                seen_artist_ids.add(artist.id)
                if not _is_public_status(artist.status):
                    continue
                if (artist.country_code or "").strip().upper() != entry.region:
                    continue

                scope = aggregates[(chart.label, entry.region)]
                current = scope.setdefault(artist.id, {
                    "artist": artist,
                    "raw_points": 0,
                    "releases": set(),
                })
                current["raw_points"] += max(int(entry.raw_total_points or 0), 0)
                current["releases"].add((chart.chart_type, entry.release_id))

    ranked_scopes = {}
    for scope_key, artists in aggregates.items():
        ranked_scopes[scope_key] = sorted(
            artists.values(),
            key=lambda item: (
                -item["raw_points"],
                -len(item["releases"]),
                (item["artist"].display_name or item["artist"].name).lower(),
                item["artist"].id,
            ),
        )

    result = defaultdict(dict)
    previous_ranks = defaultdict(dict)
    historical_peaks = {}
    ordered_scopes = sorted(
        ranked_scopes,
        key=lambda item: (period_order[item[0]], item[1]),
    )
    for label, region in ordered_scopes:
        current_ranks = {}
        rows = []
        for rank, item in enumerate(ranked_scopes[(label, region)][:50], 1):
            artist = item["artist"]
            previous_rank = previous_ranks[region].get(artist.id)
            history_key = (region, artist.id)
            appeared_before = history_key in historical_peaks
            peak_rank = min(historical_peaks.get(history_key, rank), rank)
            historical_peaks[history_key] = peak_rank
            current_ranks[artist.id] = rank
            profile = _artist_payload(request, artist)
            artist_name = artist.display_name or artist.name
            rows.append({
                "id": artist.id,
                "artist_id": artist.id,
                "r": rank,
                "t": artist_name,
                "a": "",
                "pa": artist_name,
                "p": public_points(rank),
                "rp": item["raw_points"],
                "entries_count": len(item["releases"]),
                "co": artist.country,
                "cc": artist.country_code,
                "fl": artist.flag,
                "prev_rank": previous_rank,
                "last_month": previous_rank if previous_rank is not None else "—",
                "peak_rank": peak_rank,
                "movement": _movement_value(previous_rank, rank, appeared_before),
                "primary_artists": [profile],
                "featured_artist_profiles": [],
                "is_artist_entry": True,
            })
        previous_ranks[region] = current_ranks
        result[region][label] = rows
    return {region: dict(months) for region, months in result.items()}


def _chart_data(request, charts):
    full = {
        "singles": {"combined": {}, "platforms": {}, "regions": {}},
        "albums": {"combined": {}, "platforms": {}, "regions": {}},
        "artists": {"combined": {}, "platforms": {}, "regions": {}},
    }
    months = []

    # Bulk-precompute "appeared in an earlier published month" per
    # (chart_type, scope, release_id) from data already fetched via the
    # entries/regional_entries prefetch. Avoids the N+1 .exists() query that
    # MonthlyChartEntry.movement / RegionalChartEntry.movement would
    # otherwise run once per "new" (prev_rank is None) entry — with enough
    # published months that was over a thousand extra round trips per
    # request.
    monthly_periods = defaultdict(set)
    regional_periods = defaultdict(set)
    for chart in charts:
        period = (chart.year, chart.month)
        for entry in chart.public_entries:
            monthly_periods[(chart.chart_type, entry.platform_id, entry.release_id)].add(period)
        for entry in chart.public_regional_entries:
            regional_periods[(chart.chart_type, entry.region, entry.release_id)].add(period)

    for chart in charts:
        if chart.label not in months:
            months.append(chart.label)
        chart_bucket = full.setdefault(
            chart.chart_type, {"combined": {}, "platforms": {}, "regions": {}}
        )
        period = (chart.year, chart.month)
        for entry in chart.public_entries:
            if not _is_public_status(entry.release.status) or not _is_public_status(entry.release.artist.status):
                continue
            appeared_before = any(
                p < period for p in monthly_periods[(chart.chart_type, entry.platform_id, entry.release_id)]
            )
            movement = _movement_value(entry.prev_rank, entry.rank, appeared_before)
            row = _entry_payload(request, entry, movement=movement)
            if entry.platform_id is None:
                chart_bucket["combined"].setdefault(chart.label, []).append(row)
            elif entry.platform.active:
                platform_key = entry.platform.name.upper()
                platform_bucket = chart_bucket["platforms"].setdefault(platform_key, {})
                platform_bucket.setdefault(chart.label, []).append(row)
        for entry in chart.public_regional_entries:
            if not _is_public_status(entry.release.status) or not _is_public_status(entry.release.artist.status):
                continue
            appeared_before = any(
                p < period for p in regional_periods[(chart.chart_type, entry.region, entry.release_id)]
            )
            movement = _movement_value(entry.prev_rank, entry.rank, appeared_before)
            row = _entry_payload(request, entry, movement=movement)
            region_bucket = chart_bucket["regions"].setdefault(entry.region, {})
            region_bucket.setdefault(chart.label, []).append(row)

    full["artists"]["regions"] = _regional_artist_charts(request, charts)
    return months, full


@method_decorator(never_cache, name="dispatch")
class PublicAppDataView(APIView):
    """One uncached source of truth used to hydrate the complete public app."""

    permission_classes = [AllowAny]
    authentication_classes = []

    # Keep the cache alive for 10 minutes.  Any CMS save changes the revision
    # hash so the next request builds a fresh payload automatically.
    _CACHE_TTL = 600

    def get(self, request):
        revision = _public_data_revision()
        revision_key = hashlib.sha256(revision.encode("utf-8")).hexdigest()[:24]
        cache_key = f"pub_app_data:{revision_key}"
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return _disable_response_cache(Response(cached_payload))

        public_entries = MonthlyChartEntry.objects.select_related(
            "release", "release__artist", "platform"
        ).prefetch_related(
            "release__artist_credits__artist"
        ).filter(rank__gte=1, rank__lte=50).order_by("rank")
        public_regional_entries = RegionalChartEntry.objects.select_related(
            "release", "release__artist"
        ).prefetch_related(
            "release__artist_credits__artist"
        ).filter(rank__gte=1, rank__lte=50).order_by("rank")
        regional_candidate_entries = RegionalChartEntry.objects.select_related(
            "release", "release__artist"
        ).prefetch_related(
            "release__artist_credits__artist"
        ).order_by("rank")
        charts = list(
            MonthlyChart.objects.filter(is_published=True, status="published")
            .prefetch_related(
                Prefetch("entries", queryset=public_entries, to_attr="public_entries"),
                Prefetch("regional_entries", queryset=public_regional_entries, to_attr="public_regional_entries"),
                Prefetch("regional_entries", queryset=regional_candidate_entries, to_attr="regional_candidate_entries"),
            )
            .order_by("year", "month", "chart_type")
        )
        months, full = _chart_data(request, charts)
        periods = {}
        latest_by_chart_type = {}
        for chart in charts:
            key = (chart.year, chart.month)
            period = periods.setdefault(
                key,
                {
                    "label": chart.label,
                    "year": chart.year,
                    "month": chart.month,
                    "chart_types": [],
                },
            )
            if chart.chart_type not in period["chart_types"]:
                period["chart_types"].append(chart.chart_type)
            latest_by_chart_type[chart.chart_type] = {
                "label": chart.label,
                "year": chart.year,
                "month": chart.month,
            }
        month_options = [periods[key] for key in sorted(periods)]
        latest_published_month = month_options[-1] if month_options else None

        # A region-scoped entry (e.g. Kenya) can reference a release ranked
        # outside the global Top 50, so it may not appear in public_entries —
        # both sources must feed the release/artist id sets below.
        public_release_ids = {
            entry.release_id
            for chart in charts
            for entry in list(chart.public_entries) + list(chart.public_regional_entries)
            if _is_public_status(entry.release.status)
            and _is_public_status(entry.release.artist.status)
        }
        public_artist_ids = set()
        for chart in charts:
            for entry in list(chart.public_entries) + list(chart.public_regional_entries):
                if entry.release_id not in public_release_ids:
                    continue
                credits = release_credit_payload(entry.release, entry_featured=entry.featured_artists)
                public_artist_ids.update(artist.id for artist in credits["primary_artists"])
                public_artist_ids.update(artist.id for artist in credits["featured_artists"])

        artists = [
            _artist_payload(request, artist)
            for artist in Artist.objects.filter(id__in=public_artist_ids).only(
                "id", "name", "slug", "display_name", "aliases", "country", "country_code",
                "city_region", "genre", "biography", "image", "artist_type", "verified",
                "status", "spotify_url", "apple_music_url", "youtube_url", "boomplay_url",
                "audiomack_url", "tiktok_url", "instagram_url", "x_url", "facebook_url",
                "website_url", "updated_at"
            )
            if _is_public_status(artist.status)
        ]
        releases = [
            _release_payload(request, release)
            for release in Release.objects.select_related("artist").prefetch_related("artist_credits__artist").filter(id__in=public_release_ids).only(
                "id", "title", "chart_type", "artist_id", "featured_artists", "credited_artists",
                "songwriters", "producers", "release_year", "release_date", "isrc", "upc",
                "number_of_tracks", "country", "country_code", "genre", "label", "distributor",
                "cover_image", "spotify_url", "apple_music_url", "boomplay_url", "audiomack_url",
                "youtube_url", "tiktok_url", "shazam_url", "radio_info", "status", "updated_at"
            )
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
        settings = {
            item.key: item.value
            for item in SiteSetting.objects.exclude(key__startswith="_")
        }
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
        news = news.select_related(
            "related_artist",
            "related_release",
            "related_release__artist",
        ).prefetch_related("related_release__artist_credits__artist")

        news_artists = list(
            Artist.objects.exclude(image="")
            .exclude(status__in=HIDDEN_STATUSES)
            .only("id", "name", "slug", "display_name", "aliases", "image")
        )
        news_releases = list(
            Release.objects.exclude(cover_image="")
            .exclude(status__in=HIDDEN_STATUSES)
            .select_related("artist")
            .prefetch_related("artist_credits__artist")
            .only("id", "title", "cover_image", "artist_id")
        )

        certifications = Certification.objects.select_related("release", "release__artist").prefetch_related(
            "release__artist_credits__artist"
        ).filter(is_hidden=False)

        payload = {
            "revision": revision,
            "generated_at": timezone.now(),
            "months": months,
            "month_options": month_options,
            "latest_published_month": latest_published_month,
            "latest_published_by_chart_type": latest_by_chart_type,
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
                    "media": news_media_payload(request, item, news_artists, news_releases),
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
                    "artist": release_credit_payload(item.release)["artist_credit"],
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
        cache.set(cache_key, payload, self._CACHE_TTL)
        return _disable_response_cache(Response(payload))


@method_decorator(never_cache, name="dispatch")
class PublicAppRevisionView(APIView):
    """Lightweight change signal used by an open public app to detect CMS saves."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return _disable_response_cache(Response({"revision": _public_data_revision()}))


@method_decorator(never_cache, name="dispatch")
class PublicArtistDetailView(APIView):
    """Per-artist detail endpoint for the main app's artist profile page.

    Always fetches live from the database so any CMS edit to an artist's
    biography, image, social links, etc. is immediately visible the next
    time the artist detail page is loaded.

    URL: /api/app-data/artist/<slug>/
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, slug):
        try:
            artist = Artist.objects.get(slug=slug)
        except Artist.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)

        if not _is_public_status(artist.status):
            return Response({"detail": "Not found."}, status=404)

        profile = _artist_payload(request, artist)

        # Combined-chart history across all published months (no platform breakdown).
        entries = (
            published_artist_entries(artist)
            .select_related("chart", "release", "release__artist")
            .prefetch_related("release__artist_credits__artist")
            .distinct()
            .order_by("-chart__year", "-chart__month", "rank")
        )
        history = []
        for entry in entries:
            if not _is_public_status(entry.release.status):
                continue
            history.append({
                "chart_type": entry.release.chart_type,
                "month": entry.chart.label,
                "year": entry.chart.year,
                "month_num": entry.chart.month,
                "release_id": entry.release_id,
                "title": entry.release.title,
                "artist_credit": release_credit_payload(entry.release, entry_featured=entry.featured_artists)["artist_credit"],
                "rank": entry.rank,
                "total_points": entry.total_points,
                "weeks_on_chart": entry.weeks_on_chart,
                "peak_rank": entry.peak_rank,
                "prev_rank": entry.prev_rank,
                "movement": entry.movement,
                "cover_image": _file_url(request, entry.release.cover_image),
            })

        # Aggregate stats per chart type.
        def _chart_stats(chart_type):
            agg = (
                published_artist_entries(artist)
                .filter(
                    release__chart_type=chart_type,
                )
                .distinct()
                .aggregate(total_pts=Sum("total_points"), peak=Min("rank"))
            )
            return {
                "total_points": agg["total_pts"] or 0,
                "peak_rank": agg["peak"],
            }

        releases = [
            _release_payload(request, release)
            for release in Release.objects.select_related("artist").prefetch_related("artist_credits__artist").filter(
                Q(artist_credits__artist=artist)
                | Q(artist=artist, artist_credits__isnull=True)
            ).distinct()
            if _is_public_status(release.status)
        ]

        return _disable_response_cache(Response({
            "artist": profile,
            "singles_stats": _chart_stats("singles"),
            "albums_stats": _chart_stats("albums"),
            "chart_history": history,
            "releases": releases,
        }))
