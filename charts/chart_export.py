import calendar

from django.http import JsonResponse
from django.db.models import Q
from django.views.decorators.http import require_GET

from .models import MonthlyChart, MonthlyChartEntry, Platform


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
        return JsonResponse(
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
    )

    if platform_slug == "combined":
        entries_query = entries_query.filter(platform__isnull=True)
        platform_label = "Combined"
        prior_entries = MonthlyChartEntry.objects.filter(platform__isnull=True)
    else:
        platform = Platform.objects.filter(slug=platform_slug).first()

        if not platform:
            return JsonResponse(
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
        featured_artists = (entry.featured_artists or "").strip()
        artist_name = artist.display_name or artist.name
        credit_members = [artist_name, *[name.strip() for name in featured_artists.split(",") if name.strip()]]
        if len(credit_members) <= 1:
            display_artist = credit_members[0]
        elif len(credit_members) == 2:
            display_artist = " & ".join(credit_members)
        else:
            display_artist = f"{', '.join(credit_members[:-1])} & {credit_members[-1]}"
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

    return JsonResponse(
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
