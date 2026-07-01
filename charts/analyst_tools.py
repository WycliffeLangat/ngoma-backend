import math
from collections import defaultdict

from django.db.models import Q

from .models import Certification, MonthlyChart, MonthlyChartEntry, NewsArticle
from .artist_credits import release_credit_payload


PLATFORM_COLORS = {
    "Apple Music": "#FC3C44",
    "Audiomack": "#F68B1F",
    "Boomplay": "#00FFFF",
    "Spotify": "#1DB954",
    "YouTube": "#FF0000",
    "Shazam": "#0088FF",
    "Combined": "#B8860B",
}


def _credit_members(entry):
    credits = release_credit_payload(entry.release, entry_featured=entry.featured_artists)
    return [*credits['primary_artist_names'], *credits['featured_artist_names']]


def _credit(entry):
    return release_credit_payload(entry.release, entry_featured=entry.featured_artists)['artist_credit'] or "Unknown artist"


def _lead_artist(entry):
    credits = release_credit_payload(entry.release, entry_featured=entry.featured_artists)
    return credits['primary_artists'][0] if credits['primary_artists'] else entry.release.artist


def _entry_dict(entry):
    lead_artist = _lead_artist(entry)
    return {
        "rank": entry.rank,
        "title": entry.release.title,
        "artist": _credit(entry),
        "primary_artist": lead_artist.display_name or lead_artist.name,
        "featured_artists": release_credit_payload(entry.release, entry_featured=entry.featured_artists)['featured_artist_names'],
        "country": lead_artist.country,
        "country_code": lead_artist.country_code,
        "points": entry.total_points,
        "raw_points": entry.raw_total_points,
        "previous_rank": entry.prev_rank,
        "peak_rank": entry.peak_rank,
        "platforms": entry.platform_count,
        "platforms_max": entry.platform_max,
        "weeks": entry.weeks_on_chart,
        "release_year": entry.release_year,
    }


def _latest_chart(chart_type="singles"):
    return MonthlyChart.objects.filter(
        chart_type=chart_type,
        is_published=True,
        status="published",
    ).order_by("-year", "-month").first()


def _resolve_chart(chart_type="singles", month=""):
    query = MonthlyChart.objects.filter(
        chart_type=chart_type,
        is_published=True,
        status="published",
    )
    if month:
        query = query.filter(label__iexact=month.strip())
    return query.order_by("-year", "-month").first()


def _entries_for_chart(chart, platform="Combined", limit=50):
    if not chart:
        return []
    query = MonthlyChartEntry.objects.filter(chart=chart, rank__lte=50).select_related(
        "release",
        "release__artist",
        "platform",
    ).prefetch_related("release__artist_credits__artist")
    if not platform or platform.casefold() == "combined":
        query = query.filter(platform__isnull=True)
    else:
        query = query.filter(platform__name__iexact=platform)
    return list(query.order_by("rank")[: max(1, min(int(limit or 50), 50))])


def _charts_through(chart_type="singles", through_month=""):
    cutoff = _resolve_chart(chart_type, through_month)
    query = MonthlyChart.objects.filter(
        chart_type=chart_type,
        is_published=True,
        status="published",
    )
    if cutoff:
        query = query.filter(Q(year__lt=cutoff.year) | Q(year=cutoff.year, month__lte=cutoff.month))
    return list(query.order_by("year", "month"))


def get_chart(chart_type="singles", month="", platform="Combined", limit=50):
    chart = _resolve_chart(chart_type, month)
    entries = _entries_for_chart(chart, platform, limit)
    return {
        "chart_type": chart_type,
        "month": chart.label if chart else month,
        "platform": platform or "Combined",
        "entry_count": len(entries),
        "entries": [_entry_dict(entry) for entry in entries],
        "note": "All public chart points use the Top 50 scale: #1 earns 50 and #50 earns 1.",
    }


def _artist_totals(chart_type="singles", through_month=""):
    totals = defaultdict(lambda: {
        "points": 0,
        "months": set(),
        "release_ids": set(),
        "best_rank": 999,
        "best_release": "",
        "country": "",
        "country_code": "",
        "history": [],
    })
    charts = _charts_through(chart_type, through_month)
    for chart in charts:
        entries = MonthlyChartEntry.objects.filter(
            chart=chart,
            platform__isnull=True,
            rank__lte=50,
        ).select_related("release", "release__artist").prefetch_related("release__artist_credits__artist")
        month_points = defaultdict(int)
        for entry in entries:
            for name in _credit_members(entry):
                row = totals[name]
                row["points"] += entry.total_points
                row["months"].add(chart.label)
                row["release_ids"].add(entry.release_id)
                month_points[name] += entry.total_points
                if entry.rank < row["best_rank"]:
                    row["best_rank"] = entry.rank
                    row["best_release"] = entry.release.title
                lead_artist = _lead_artist(entry)
                if name.casefold() in {
                    lead_artist.name.casefold(),
                    (lead_artist.display_name or '').casefold(),
                }:
                    row["country"] = lead_artist.country
                    row["country_code"] = lead_artist.country_code
        for name, points in month_points.items():
            totals[name]["history"].append({"month": chart.label, "points": points})
    ranked = sorted(totals.items(), key=lambda item: (-item[1]["points"], item[0].casefold()))
    return {
        name: {
            **row,
            "rank": index + 1,
            "months": len(row["months"]),
            "entries": len(row["release_ids"]),
            "release_ids": None,
        }
        for index, (name, row) in enumerate(ranked)
    }


def get_artist_profile(name, chart_type="singles", through_month=""):
    profiles = _artist_totals(chart_type, through_month)
    matched_name = next((artist for artist in profiles if artist.casefold() == name.strip().casefold()), None)
    if not matched_name:
        candidates = [artist for artist in profiles if name.strip().casefold() in artist.casefold()][:10]
        return {"found": False, "query": name, "candidates": candidates}
    row = profiles[matched_name]
    return {
        "found": True,
        "name": matched_name,
        "chart_type": chart_type,
        "through_month": through_month or (_latest_chart(chart_type).label if _latest_chart(chart_type) else ""),
        "artist_rank": row["rank"],
        "credited_points": row["points"],
        "entries": row["entries"],
        "months": row["months"],
        "best_entry_rank": row["best_rank"],
        "best_release": row["best_release"],
        "country": row["country"],
        "country_code": row["country_code"],
        "monthly_points": row["history"],
        "credit_note": "Primary, featured, and joint credits each receive the release's full Display Points.",
    }


def get_release_profile(title, chart_type="singles"):
    entries = list(MonthlyChartEntry.objects.filter(
        chart__chart_type=chart_type,
        chart__is_published=True,
        chart__status="published",
        platform__isnull=True,
        rank__lte=50,
        release__title__iexact=title.strip(),
    ).select_related("chart", "release", "release__artist").order_by("chart__year", "chart__month"))
    if not entries:
        candidates = list(MonthlyChartEntry.objects.filter(
            chart__chart_type=chart_type,
            platform__isnull=True,
            release__title__icontains=title.strip(),
        ).values_list("release__title", flat=True).distinct()[:10])
        return {"found": False, "query": title, "candidates": candidates}
    latest = entries[-1]
    platforms = defaultdict(list)
    platform_entries = MonthlyChartEntry.objects.filter(
        chart__chart_type=chart_type,
        chart__is_published=True,
        chart__status="published",
        release_id=latest.release_id,
        platform__isnull=False,
        rank__lte=50,
    ).select_related("chart", "platform").order_by("chart__year", "chart__month", "rank")
    for entry in platform_entries:
        platforms[entry.platform.name].append({
            "month": entry.chart.label,
            "rank": entry.rank,
            "points": entry.total_points,
        })
    total_points = sum(entry.total_points for entry in entries)
    return {
        "found": True,
        "title": latest.release.title,
        "artist": _credit(latest),
        "primary_artist": _lead_artist(latest).display_name or _lead_artist(latest).name,
        "chart_type": chart_type,
        "total_display_points": total_points,
        "certification": "Diamond" if total_points >= 600 else "Platinum" if total_points >= 400 else "Gold" if total_points >= 200 else "Not certified",
        "peak_rank": min(entry.rank for entry in entries),
        "months_charted": len(entries),
        "latest_rank": latest.rank,
        "latest_month": latest.chart.label,
        "combined_history": [
            {
                "month": entry.chart.label,
                "rank": entry.rank,
                "points": entry.total_points,
                "platforms": entry.platform_count,
                "platforms_max": entry.platform_max,
            }
            for entry in entries
        ],
        "platform_history": dict(platforms),
    }


def get_platform_analysis(chart_type="singles", month=""):
    chart = _resolve_chart(chart_type, month)
    combined = _entries_for_chart(chart, "Combined", 50)
    combined_ids = {entry.release_id for entry in combined}
    rows = []
    platform_names = MonthlyChartEntry.objects.filter(
        chart=chart,
        platform__isnull=False,
    ).order_by().values_list("platform__name", flat=True).distinct() if chart else []
    for platform in platform_names:
        platform_entries = _entries_for_chart(chart, platform, 50)
        rows.append({
            "platform": platform,
            "color": PLATFORM_COLORS.get(platform, "#69716B"),
            "combined_entries_contributed": sum(entry.release_id in combined_ids for entry in platform_entries),
            "number_one": _entry_dict(platform_entries[0]) if platform_entries else None,
            "top_50_size": len(platform_entries),
        })
    rows.sort(key=lambda item: (-item["combined_entries_contributed"], item["platform"]))
    return {
        "chart_type": chart_type,
        "month": chart.label if chart else month,
        "platforms": rows,
    }


def predict_next_month(chart_type="singles", title="", artist="", count=10):
    latest = _latest_chart(chart_type)
    if not latest:
        return {"predictions": [], "method": "No chart data available."}
    current_entries = _entries_for_chart(latest, "Combined", 50)
    candidates = current_entries
    if title:
        candidates = [entry for entry in candidates if entry.release.title.casefold() == title.strip().casefold()]
    if artist:
        candidates = [entry for entry in candidates if any(member.casefold() == artist.strip().casefold() for member in _credit_members(entry))]
    predictions = []
    for current in candidates:
        history = list(MonthlyChartEntry.objects.filter(
            chart__chart_type=chart_type,
            chart__is_published=True,
            chart__status="published",
            platform__isnull=True,
            release_id=current.release_id,
            rank__lte=50,
        ).select_related("chart", "release", "release__artist").order_by("chart__year", "chart__month"))
        recent = history[-4:]
        improvements = [recent[index - 1].rank - recent[index].rank for index in range(1, len(recent))]
        weighted_improvement = 0
        if improvements:
            weights = list(range(1, len(improvements) + 1))
            weighted_improvement = sum(value * weight for value, weight in zip(improvements, weights)) / sum(weights)
        coverage_ratio = current.platform_count / max(current.platform_max, 1)
        coverage_adjustment = (coverage_ratio - 0.5) * 2.5
        predicted_rank = round(current.rank - (weighted_improvement * 0.65) - coverage_adjustment)
        predicted_rank = max(1, min(50, predicted_rank))
        volatility = 0
        if len(recent) > 1:
            mean_rank = sum(entry.rank for entry in recent) / len(recent)
            volatility = math.sqrt(sum((entry.rank - mean_rank) ** 2 for entry in recent) / len(recent))
        confidence = "medium" if len(recent) >= 3 and volatility <= 10 else "low"
        predictions.append({
            "title": current.release.title,
            "artist": _credit(current),
            "current_rank": current.rank,
            "estimated_next_rank": predicted_rank,
            "estimated_change": current.rank - predicted_rank,
            "confidence": confidence,
            "recent_history": [{"month": entry.chart.label, "rank": entry.rank} for entry in recent],
            "coverage": f"{current.platform_count}/{current.platform_max}",
        })
    predictions.sort(key=lambda item: (item["estimated_next_rank"], item["current_rank"]))
    return {
        "based_on_month": latest.label,
        "forecast_month": "next available month after the current dataset",
        "predictions": predictions[: max(1, min(int(count or 10), 20))],
        "method": "Transparent heuristic using recent Combined rank momentum and current platform coverage. It is an estimate, not a known future result.",
    }


def get_app_overview(chart_type="singles", through_month=""):
    charts = _charts_through(chart_type, through_month)
    latest = charts[-1] if charts else None
    artist_profiles = _artist_totals(chart_type, latest.label if latest else through_month)
    top_artists = sorted(artist_profiles.items(), key=lambda item: item[1]["rank"])[:10]
    release_totals = defaultdict(lambda: {"points": 0, "title": "", "artist": "", "peak": 999})
    country_totals = defaultdict(int)
    monthly_leaders = []
    for chart in charts:
        entries = _entries_for_chart(chart, "Combined", 50)
        if entries:
            monthly_leaders.append({"month": chart.label, **_entry_dict(entries[0])})
        for entry in entries:
            row = release_totals[entry.release_id]
            row["points"] += entry.total_points
            row["title"] = entry.release.title
            row["artist"] = _credit(entry)
            row["peak"] = min(row["peak"], entry.rank)
            country_totals[_lead_artist(entry).country_code or "Unknown"] += 1
    top_releases = sorted(release_totals.values(), key=lambda row: (-row["points"], row["peak"]))[:10]
    certifications = Certification.objects.filter(release__chart_type=chart_type)
    news = list(NewsArticle.objects.filter(is_published=True).values("title", "category", "published_at")[:20])
    return {
        "dataset_period": f"{charts[0].label} to {charts[-1].label}" if charts else "No published charts",
        "chart_type": chart_type,
        "months": [chart.label for chart in charts],
        "combined_rows": sum(len(_entries_for_chart(chart, "Combined", 50)) for chart in charts),
        "current_chart": get_chart(chart_type, latest.label, "Combined", 10) if latest else None,
        "monthly_number_ones": monthly_leaders,
        "top_cumulative_artists": [
            {"rank": row["rank"], "name": name, "points": row["points"], "entries": row["entries"]}
            for name, row in top_artists
        ],
        "top_cumulative_releases": top_releases,
        "current_platform_analysis": get_platform_analysis(chart_type, latest.label) if latest else None,
        "country_entry_counts": dict(sorted(country_totals.items(), key=lambda item: -item[1])),
        "certification_counts": {
            level: certifications.filter(level=level).count()
            for level in ("gold", "platinum", "diamond")
        },
        "latest_news": [
            {**item, "published_at": item["published_at"].isoformat()}
            for item in news
        ],
        "methodology": {
            "combined_chart_size": 50,
            "combined_display_points": "#1 earns 50 down to #50 earning 1",
            "singles_platforms": 6,
            "albums_platforms": 2,
            "certifications": {"gold": 200, "platinum": 400, "diamond": 600},
            "artist_credit": "Every credited primary, featured, or joint artist receives the release's full Display Points.",
        },
    }


TOOL_HANDLERS = {
    "get_app_overview": get_app_overview,
    "get_chart": get_chart,
    "get_artist_profile": get_artist_profile,
    "get_release_profile": get_release_profile,
    "get_platform_analysis": get_platform_analysis,
    "predict_next_month": predict_next_month,
}


ANALYST_TOOLS = [
    {
        "type": "function",
        "name": "get_app_overview",
        "description": "Review an app-wide summary of charts, leaders, artists, releases, platforms, countries, certifications, news, and methodology. Use for broad or ambiguous questions.",
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": ["singles", "albums"]},
                "through_month": {"type": "string", "description": "Month label such as May 2026, or empty for the latest month."},
            },
            "required": ["chart_type", "through_month"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_chart",
        "description": "Get a specific Combined or individual-platform Top 50 chart with ranks and metadata.",
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": ["singles", "albums"]},
                "month": {"type": "string", "description": "Month label, or empty for latest."},
                "platform": {"type": "string", "description": "Combined, Apple Music, Audiomack, Boomplay, Spotify, YouTube, or Shazam."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["chart_type", "month", "platform", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_artist_profile",
        "description": "Get a cumulative artist ranking and history. Includes primary, featured, and joint artist credits.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "chart_type": {"type": "string", "enum": ["singles", "albums"]},
                "through_month": {"type": "string", "description": "Month label, or empty for latest."},
            },
            "required": ["name", "chart_type", "through_month"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_release_profile",
        "description": "Get a song or album's Combined and platform histories, points, peak, and certification.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "chart_type": {"type": "string", "enum": ["singles", "albums"]},
            },
            "required": ["title", "chart_type"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_platform_analysis",
        "description": "Compare platform #1s and how many entries each platform contributed to the Combined Top 50.",
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": ["singles", "albums"]},
                "month": {"type": "string", "description": "Month label, or empty for latest."},
            },
            "required": ["chart_type", "month"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "predict_next_month",
        "description": "Generate a transparent next-month rank estimate from current app data. Predictions are heuristic and must be labeled as estimates.",
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": ["singles", "albums"]},
                "title": {"type": "string", "description": "Exact release title, or empty for an overall forecast."},
                "artist": {"type": "string", "description": "Exact credited artist, or empty."},
                "count": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["chart_type", "title", "artist", "count"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]
