import json

from charts.models import MonthlyChart, MonthlyChartEntry, RegionalChartEntry, Platform, Release, Artist

ARTIST_CORE_FIELDS = ["country", "country_code", "city_region", "genre", "biography"]
RELEASE_COMMON_CORE_FIELDS = ["genre", "label", "distributor", "country", "country_code"]
RELEASE_EXTRA_FIELDS = {
    "singles": ["songwriters", "producers", "isrc"],
    "albums": ["number_of_tracks", "upc"],
}

SINGLES_PLATFORM_SLUGS = ["apple-music", "audiomack", "boomplay", "shazam", "spotify", "youtube"]
ALBUMS_PLATFORM_SLUGS = ["apple-music", "audiomack"]

def release_missing_core_fields(release):
    extra_fields = RELEASE_EXTRA_FIELDS[release.chart_type]
    missing = [f for f in RELEASE_COMMON_CORE_FIELDS if not (getattr(release, f) or "").strip()]
    for field in extra_fields:
        value = getattr(release, field)
        is_blank = value in (None, "", 0) if field == "number_of_tracks" else not (value or "").strip()
        if is_blank:
            missing.append(field)
    if not release.release_year:
        missing.append("release_year")
    if not release.release_date:
        missing.append("release_date")
    return missing

def artist_missing_core_fields(artist):
    return [f for f in ARTIST_CORE_FIELDS if not (getattr(artist, f) or "").strip()]

result = {"scopes": {}, "releases": {}, "artists": {}}

for chart_type, platform_slugs in [("singles", SINGLES_PLATFORM_SLUGS), ("albums", ALBUMS_PLATFORM_SLUGS)]:
    chart = MonthlyChart.objects.get(year=2026, month=8, chart_type=chart_type)

    combined_new = list(
        MonthlyChartEntry.objects.filter(chart=chart, platform__isnull=True, rank__lte=50, prev_rank__isnull=True)
        .select_related("release", "release__artist")
        .order_by("rank")
    )
    result["scopes"][f"{chart_type} - Combined"] = [e.release_id for e in combined_new]

    kenya_new = list(
        RegionalChartEntry.objects.filter(chart=chart, region="KE", rank__lte=50, prev_rank__isnull=True)
        .select_related("release", "release__artist")
        .order_by("rank")
    )
    result["scopes"][f"{chart_type} - Kenya"] = [e.release_id for e in kenya_new]

    for slug in platform_slugs:
        platform = Platform.objects.get(slug=slug)
        plat_new = list(
            MonthlyChartEntry.objects.filter(chart=chart, platform=platform, rank__lte=50, prev_rank__isnull=True)
            .select_related("release", "release__artist")
            .order_by("rank")
        )
        result["scopes"][f"{chart_type} - {platform.name}"] = [e.release_id for e in plat_new]

all_release_ids = set()
for ids in result["scopes"].values():
    all_release_ids.update(ids)

all_artist_ids = set()
for release in Release.objects.filter(id__in=all_release_ids).select_related("artist").order_by("artist__name", "title"):
    missing = release_missing_core_fields(release)
    all_artist_ids.add(release.artist_id)
    if not missing:
        continue
    result["releases"][release.id] = {
        "title": release.title,
        "artist": release.artist.name,
        "artist_id": release.artist_id,
        "chart_type": release.chart_type,
        "missing_fields": missing,
    }

for artist in Artist.objects.filter(id__in=all_artist_ids).order_by("name"):
    missing = artist_missing_core_fields(artist)
    if missing:
        result["artists"][artist.id] = {"name": artist.name, "missing_fields": missing}

with open("scripts/new_top50_aug2026_report.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("scopes:", {k: len(v) for k, v in result["scopes"].items()})
print("distinct releases needing core research:", len(result["releases"]))
print("distinct artists needing core research:", len(result["artists"]))
