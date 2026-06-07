import calendar

from django.http import JsonResponse
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

    entries_query = MonthlyChartEntry.objects.filter(chart=chart).select_related(
        "release",
        "release__artist",
        "platform",
    )

    if platform_slug == "combined":
        entries_query = entries_query.filter(platform__isnull=True)
        platform_label = "Combined"
    else:
        platform = Platform.objects.filter(slug=platform_slug).first()

        if not platform:
            return JsonResponse(
                {"error": f"Platform '{platform_slug}' was not found."},
                status=404,
            )

        entries_query = entries_query.filter(platform=platform)
        platform_label = platform.name

    entries = []

    for entry in entries_query.order_by("rank"):
        release = entry.release
        artist = release.artist
        artist_country_code = (artist.country_code or "").strip().upper()
        artist_country = artist.country or ""

        entries.append(
            {
                "id": entry.id,
                "rank": entry.rank,
                "title": release.title,
                "artist": artist.name,
                "artist_country": artist_country,
                "artist_country_code": artist_country_code,
                "artist_flag": country_code_to_flag(artist_country_code),
                "movement": format_movement(entry),
                "last_month": format_last_month(entry),
                "prev_rank": entry.prev_rank,
                "weeks_on_chart": entry.weeks_on_chart,
                "platform_count": entry.platform_count,
                "peak_rank": entry.peak_rank,
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
