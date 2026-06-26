import calendar

from django.http import JsonResponse
from django.db.models import Q
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from .models import MonthlyChart, MonthlyChartEntry, Platform
from .artist_credits import release_credit_payload


def _no_cache_json(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def format_movement(entry):
    if entry.prev_rank is None:
        return "NEW"

    difference = entry.prev_rank - entry.rank

    if difference > 0:
        return f"▲ {difference}"

    if difference < 0:
        return f"▼ {abs(difference)}"

    return "—"


def format_last_month(entry):
    if entry.prev_rank is None:
        return "—"

    return entry.prev_rank


def country_code_to_flag(country_code):
    code = (country_code or "").strip().upper()

    if len(code) != 2 or not code.isalpha():
        return "🌍"

    return "".join(chr(127397 + ord(char)) for char in code)


@never_cache
@require_GET
def chart_image_data(request):
    chart_type = request.GET.get("type", "singles").lower()
    year = request.GET.get("year")
    month = request.GET.get("month")
    platform_slug = request.GET.get("platform", "combined").lower()

    chart_query = MonthlyChart.objects.filter(
        chart_type=chart_type,
        is_published=True,
        status="published",
    )

    if year:
        chart_query = chart_query.filter(year=int(year))

    if month:
        chart_query = chart_query.filter(month=int(month))

    chart = chart_query.order_by("-year", "-month").first()

    if not chart:
        return _no_cache_json(
            {
                "error": "No published chart found for the selected filters.",
                "chart_type": chart_type,
                "year": year,
                "month": month,
            },
            status=404,
        )

    entries_query = MonthlyChartEntry.objects.filter(chart=chart).exclude(
        release__status__in=["archived", "inactive", "rejected", "draft"],
    ).exclude(
        release__artist__status__in=["archived", "inactive", "rejected", "draft"],
    ).select_related(
        "release",
        "release__artist",
        "platform",
    ).prefetch_related("release__artist_credits__artist")

    if platform_slug == "combined":
        entries_query = entries_query.filter(platform__isnull=True)
        platform_label = "Combined"
        prior_entries = MonthlyChartEntry.objects.filter(platform__isnull=True)
    else:
        platform = Platform.objects.filter(slug=platform_slug).first()

        if not platform:
            return _no_cache_json(
                {"error": f"Platform '{platform_slug}' was not found."},
                status=404,
            )

        entries_query = entries_query.filter(platform=platform)
        platform_label = platform.name
        prior_entries = MonthlyChartEntry.objects.filter(platform=platform)

    prior_release_ids = set(
        prior_entries.filter(chart__chart_type=chart.chart_type, rank__lte=50)
        .filter(Q(chart__year__lt=chart.year) | Q(chart__year=chart.year, chart__month__lt=chart.month))
        .values_list("release_id", flat=True)
    )

    entries_query = entries_query.filter(rank__lte=50)
    entries = []

    for entry in entries_query.order_by("rank"):
        release = entry.release
        artist = release.artist
        featured_artists = (release.featured_artists or entry.featured_artists or "").strip()
        artist_name = artist.display_name or artist.name
        credits = release_credit_payload(release, entry_featured=featured_artists)
        display_artist = credits["artist_credit"]
        artist_country_code = (artist.country_code or "").strip().upper()
        artist_country = artist.country or ""

        entries.append(
            {
                "id": entry.id,
                "rank": entry.rank,
                "title": release.title,
                "artist": display_artist,
                "primary_artist": artist_name,
                "featured_artists": featured_artists,
                "artist_credit": credits["artist_credit"],
                "primary_artist_credit": credits["primary_artist_credit"],
                "featured_artist_credit": credits["featured_artist_credit"],
                "primary_artists": [
                    {"id": item.id, "name": item.display_name or item.name, "slug": item.slug}
                    for item in credits["primary_artists"]
                ],
                "featured_artist_profiles": [
                    {"id": item.id, "name": item.display_name or item.name, "slug": item.slug}
                    for item in credits["featured_artists"]
                ],
                "artist_country": artist_country,
                "artist_country_code": artist_country_code,
                "artist_flag": country_code_to_flag(artist_country_code),
                "total_points": entry.total_points,
                "movement": "RE" if entry.prev_rank is None and entry.release_id in prior_release_ids else format_movement(entry),
                "last_month": format_last_month(entry),
                "prev_rank": entry.prev_rank,
                "weeks_on_chart": entry.weeks_on_chart,
                "platform_count": entry.platform_count,
                "platform_max": entry.platform_max,
                "peak_rank": entry.peak_rank,
                "release_year": entry.release_year,
                "confidence": entry.confidence,
                "release_id": release.id,
                "artist_id": artist.id,
                "release_date": release.release_date,
                "genre": release.genre,
                "label": release.label,
                "distributor": release.distributor,
                "cover_image": request.build_absolute_uri(release.cover_image.url) if release.cover_image else "",
                "isrc": release.isrc,
                "upc": release.upc,
                "number_of_tracks": release.number_of_tracks,
                "songwriters": release.songwriters,
                "producers": release.producers,
                "spotify_url": release.spotify_url,
                "apple_music_url": release.apple_music_url,
                "boomplay_url": release.boomplay_url,
                "audiomack_url": release.audiomack_url,
                "youtube_url": release.youtube_url,
                "tiktok_url": release.tiktok_url,
                "shazam_url": release.shazam_url,
                "radio_info": release.radio_info,
                "chart_type": chart.chart_type,
                "platform": platform_label,
            }
        )

    return _no_cache_json(
        {
            "chart_id": chart.id,
            "chart_type": chart.chart_type,
            "chart_type_label": chart.get_chart_type_display(),
            "year": chart.year,
            "month": chart.month,
            "month_name": calendar.month_name[chart.month],
            "label": chart.label,
            "platform": platform_label,
            "entry_count": len(entries),
            "entries": entries,
        }
    )
