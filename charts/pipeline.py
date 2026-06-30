"""
Data cleaning and processing pipeline for Ngoma Charts.
Converts raw xlsx weekly data into normalized chart entries.
"""
import re
import openpyxl
from collections import defaultdict, Counter
from django.db import transaction
from .models import (
    Platform, Artist, Release, WeeklyUpload, MonthlyChart,
    PlatformChartEntry, MonthlyChartEntry, NormalizationRule,
    ChartType, Certification
)


# ── NORMALIZATION RULES (loaded from DB + hardcoded fallbacks) ──────────────

ARTIST_NORM_DEFAULTS = {
    'ayra': 'Ayra Starr', 'willy': 'Willy Paul', 'kendrick': 'Kendrick Lamar',
    'adekunle': 'Adekunle Gold', 'fally': 'Fally Ipupa', 'd-voice': 'D Voice',
    'd voice': 'D Voice', 'vybz kartela': 'Vybz Kartel', 'shensea': 'Shenseea',
    'ogaobinna': 'OgaObinna', 'ogaobinna the oga@dtop': 'OgaObinna',
    'johnny': 'Johnny Drille', 'othicho': 'Othicho Jasuba',
    'stanley': 'Stanley & The Turbines', 'years': 'Years & Years',
    'papi clever': 'Papi Clever & Dorcas', 'miles': 'Miles Away',
    "nikita kering'": 'Nikita Kering', 'playboy carti': 'Playboi Carti',
    'bella kombo': 'Bella Kombo', 'bien, scar': 'Bien ft. Scar',
    'brent': 'Brent Morgan', 'nandy, billnass': 'Nandy ft. Billnass',
    'rose': 'ROSÉ', 'rosé': 'ROSÉ',
    'joel a. lwaga': 'Joel Lwaga', 'mr. tee': 'Mr.Tee',
    'dj wizzy': 'DJ WIZZY 254', 'geniusjini': 'Geniusjini x66',
}

TITLE_NORM_DEFAULTS = {
    'wa peke yangu': 'Wa Pekee Yangu', 'tipsi': 'Tipsy', 'ti ti ti': 'Tititi',
    'angel numbers/ ten toes': 'Angel Numbers / Ten Toes',
    'favourite girl(with rema)': 'Favourite Girl (with Rema)',
    'all redd': 'ALL RED', 'hii sio ndoto yangu': 'Hii Siyo Ndoto Yangu',
    'yebo lapho (gago)': 'Yebo Lapho (Gogo)', 'yebo lapho': 'Yebo Lapho (Gogo)',
    'hera onge wuon go': 'Hera Onge Wuon', 'bring me back [sped up]': 'Bring Me Back',
    'nita amini': 'Nitaamini', 'anguka nayo remix ( mashup)': 'ANGUKA NAYO REMIX (MASHUP)',
    'walewale': 'Wale Wale', 'now you know(umeniknow)': 'NOW YOU KNOW (UMENIKNOW)',
    'unanchekesha (move on)': 'UNANCHEKESHA (Move On)',
    'unanichekesha (move on)': 'UNANCHEKESHA (Move On)',
}


def get_norm_rules():
    """Load normalization rules from database, fall back to defaults."""
    artist_rules = dict(ARTIST_NORM_DEFAULTS)
    title_rules = dict(TITLE_NORM_DEFAULTS)
    for rule in NormalizationRule.objects.all():
        if rule.rule_type == 'artist':
            artist_rules[rule.raw_value.lower()] = rule.canonical_value
        else:
            title_rules[rule.raw_value.lower()] = rule.canonical_value
    return artist_rules, title_rules


def split_song_artist(raw, is_album=False):
    """Split 'Title - Artist' string."""
    raw = raw.strip()
    raw = re.sub(r'\s+', ' ', raw)
    if raw == "Kudade - Fancy Fingers Refix - Fancy Fingers":
        return "Kudade (Fancy Fingers Refix)", "Fancy Fingers"
    if raw.upper() == "BAHATI - CHERIE":
        return "Cherie", "Bahati"
    if ' - ' in raw:
        if is_album:
            idx = raw.rfind(' - ')
            return raw[:idx].strip(), raw[idx+3:].strip()
        else:
            parts = raw.split(' - ', 1)
            return parts[0].strip(), parts[1].strip()
    m = re.match(r'^(.+?)\s*-\s*(.+)$', raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw, ''


def normalize_entry(title, artist, artist_rules, title_rules, is_album=False):
    """Apply normalization rules and return canonical values + key."""
    artist = artist.strip().strip('*').strip()
    title = title.strip().strip('*').strip()
    a_low = artist.lower().strip()
    t_low = title.lower().strip()

    canonical_artist = artist_rules.get(a_low, artist)
    canonical_title = title_rules.get(t_low, title)

    if is_album:
        # Strip EP suffix
        canonical_title = re.sub(r'\s*-\s*EP\s*$', '', canonical_title, flags=re.IGNORECASE).strip()
        # Strip (Live) suffix — merge with original
        canonical_title = re.sub(r'\s*\(Live\)\s*$', '', canonical_title, flags=re.IGNORECASE).strip()

    # Lifestyle special case
    if canonical_title.lower() == 'lifestyle' and canonical_artist.lower() in ('bien', 'bien ft. scar', 'bien, scar'):
        canonical_artist = 'Bien ft. Scar'

    key = (canonical_title.lower().strip(), canonical_artist.lower().strip())
    return canonical_title, canonical_artist, key


def get_or_create_artist(name):
    from django.utils.text import slugify
    base_slug = slugify(name)[:50]
    slug = base_slug
    i = 1
    while Artist.objects.filter(slug=slug).exclude(name=name).exists():
        suffix = f"-{i}"
        slug = f"{base_slug[:50 - len(suffix)]}{suffix}"
        i += 1
    artist, _ = Artist.objects.get_or_create(name=name, defaults={'slug': slug})
    return artist


def get_or_create_release(title, artist_obj, chart_type):
    canonical = title.lower().strip()
    try:
        return Release.objects.get(canonical_title=canonical, artist=artist_obj, chart_type=chart_type)
    except Release.DoesNotExist:
        return Release.objects.create(
            title=title, artist=artist_obj, chart_type=chart_type,
            canonical_title=canonical
        )


@transaction.atomic
def process_weekly_upload(upload: WeeklyUpload, file_obj=None) -> dict:
    """
    Process a weekly xlsx upload:
    1. Parse the file
    2. Normalize all entries
    3. Deduplicate within week/platform
    4. Save PlatformChartEntry records
    5. Rebuild MonthlyChartEntry aggregates for this month
    """
    is_album = upload.chart_type == ChartType.ALBUMS
    artist_rules, title_rules = get_norm_rules()

    source = file_obj
    close_source = False
    if source is None:
        try:
            source = upload.file.open('rb')
            close_source = True
        except (NotImplementedError, FileNotFoundError, ValueError, OSError) as exc:
            raise ValueError('The original weekly workbook is unavailable. Upload the file again.') from exc
    if hasattr(source, 'seek'):
        source.seek(0)
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
        if close_source:
            upload.file.close()
    if not rows:
        raise ValueError('The workbook is empty.')
    headers = [str(h).strip() if h else '' for h in rows[0]]
    data_rows = rows[1:]

    # Get active platforms for this chart type
    if is_album:
        platform_names = ['Apple Music', 'Audiomack']
    else:
        platform_names = ['Apple Music', 'Audiomack', 'Boomplay', 'Spotify', 'YouTube', 'Shazam']

    platforms = {p.name: p for p in Platform.objects.filter(name__in=platform_names)}
    platform_col = {h: i for i, h in enumerate(headers)}
    recognized = [name for name in platform_names if name in platform_col]
    if not recognized:
        expected = ', '.join(platform_names)
        raise ValueError(f'No supported platform columns found. Expected one or more of: {expected}.')
    configured = [name for name in recognized if name in platforms]
    if not configured:
        raise ValueError('The workbook columns are valid, but the matching platforms are not configured.')

    # Clear existing entries for this upload
    PlatformChartEntry.objects.filter(upload=upload).delete()

    total_processed = 0
    total_dupes = 0

    for plat_name in platform_names:
        if plat_name not in platform_col or plat_name not in platforms:
            continue
        plat = platforms[plat_name]
        col_i = platform_col[plat_name]
        pts_base = plat.points_base

        week_entries = []
        pos = 0
        for row in data_rows:
            cell = row[col_i] if col_i < len(row) else None
            if cell and str(cell).strip():
                pos += 1
                raw = str(cell).strip()
                title_raw, artist_raw = split_song_artist(raw, is_album)
                points = pts_base - pos
                canon_title, canon_artist, key = normalize_entry(
                    title_raw, artist_raw, artist_rules, title_rules, is_album
                )
                week_entries.append((key, canon_title, canon_artist, points, pos, title_raw, artist_raw))

        # Deduplicate: keep highest position (lowest pos number)
        seen = {}
        for entry in week_entries:
            key, ct, ca, pts, pos, rt, ra = entry
            if key not in seen or pos < seen[key][3]:
                if key in seen:
                    total_dupes += 1
                seen[key] = (ct, ca, pts, pos, rt, ra)
            else:
                total_dupes += 1

        # Save entries
        for key, (ct, ca, pts, pos, rt, ra) in seen.items():
            artist_obj = get_or_create_artist(ca)
            release_obj = get_or_create_release(ct, artist_obj, upload.chart_type)
            PlatformChartEntry.objects.create(
                upload=upload, platform=plat, release=release_obj,
                position=pos, points=pts, raw_title=rt, raw_artist=ra
            )
            total_processed += 1

    upload.processed = True
    upload.duplicates_dropped = total_dupes
    upload.entries_processed = total_processed
    upload.save()

    # Rebuild monthly aggregates
    result = rebuild_monthly_chart(upload.chart_type, upload.year, upload.month)
    result['dupes_dropped'] = total_dupes
    result['entries_processed'] = total_processed
    return result


@transaction.atomic
def rebuild_monthly_chart(chart_type: str, year: int, month: int) -> dict:
    """
    Aggregate all weekly uploads for a month into MonthlyChartEntry records.
    """
    import calendar
    uploads = WeeklyUpload.objects.filter(
        chart_type=chart_type, year=year, month=month, processed=True
    )
    if not uploads.exists():
        return {'error': 'No processed uploads for this period'}

    is_album = chart_type == ChartType.ALBUMS
    if is_album:
        platform_names = ['Apple Music', 'Audiomack']
    else:
        platform_names = ['Apple Music', 'Audiomack', 'Boomplay', 'Spotify', 'YouTube', 'Shazam']

    platforms = {p.name: p for p in Platform.objects.filter(name__in=platform_names)}

    # Get or create monthly chart
    chart_label = f"{calendar.month_name[month]} {year}"
    chart, _ = MonthlyChart.objects.get_or_create(
        year=year, month=month, chart_type=chart_type,
        defaults={'label': chart_label}
    )

    # Clear existing monthly entries
    MonthlyChartEntry.objects.filter(chart=chart).delete()

    # Per-platform aggregation
    platform_agg = {p: defaultdict(lambda: {'pts': 0, 'wks': 0, 'peak': 999}) for p in platform_names}
    combined_agg = defaultdict(lambda: {'pts': 0, 'plats': set(), 'wks': 0, 'peak': 999})

    for upload in uploads:
        entries = PlatformChartEntry.objects.filter(upload=upload).select_related('release', 'platform')
        releases_seen_this_week = set()
        for e in entries:
            pn = e.platform.name
            rid = e.release.id
            platform_agg[pn][rid]['pts'] += e.points
            platform_agg[pn][rid]['wks'] += 1
            if e.position < platform_agg[pn][rid]['peak']:
                platform_agg[pn][rid]['peak'] = e.position
            combined_agg[rid]['pts'] += e.points
            combined_agg[rid]['plats'].add(pn)
            if e.position < combined_agg[rid]['peak']:
                combined_agg[rid]['peak'] = e.position
            if rid not in releases_seen_this_week:
                combined_agg[rid]['wks'] += 1
                releases_seen_this_week.add(rid)

    # Get prev month for movement calculation
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    try:
        prev_chart = MonthlyChart.objects.get(year=prev_year, month=prev_month, chart_type=chart_type)
    except MonthlyChart.DoesNotExist:
        prev_chart = None

    def get_prev_rank(release_id, platform=None):
        if not prev_chart:
            return None
        try:
            e = MonthlyChartEntry.objects.get(chart=prev_chart, release_id=release_id, platform=platform)
            return e.rank
        except MonthlyChartEntry.DoesNotExist:
            return None

    entries_to_create = []

    # Create platform entries
    for pn, plat in platforms.items():
        ranked = sorted(platform_agg[pn].items(), key=lambda x: x[1]['pts'], reverse=True)
        for rank, (rid, data) in enumerate(ranked, 1):
            prev = get_prev_rank(rid, plat)
            entries_to_create.append(MonthlyChartEntry(
                chart=chart, platform=plat, release_id=rid,
                rank=rank, total_points=data['pts'],
                weeks_on_chart=data['wks'], platform_count=1,
                peak_rank=data['peak'], prev_rank=prev
            ))

    # Create combined entries
    ranked_combined = sorted(combined_agg.items(), key=lambda x: x[1]['pts'], reverse=True)
    for rank, (rid, data) in enumerate(ranked_combined, 1):
        prev = get_prev_rank(rid, None)
        entries_to_create.append(MonthlyChartEntry(
            chart=chart, platform=None, release_id=rid,
            rank=rank, total_points=data['pts'],
            weeks_on_chart=data['wks'],
            platform_count=len(data['plats']),
            peak_rank=data['peak'], prev_rank=prev
        ))

    MonthlyChartEntry.objects.bulk_create(entries_to_create, batch_size=500)

    # Auto-certify releases
    award_certifications(chart_type)

    return {
        'chart': str(chart),
        'platform_entries': sum(len(platform_agg[p]) for p in platform_names),
        'combined_entries': len(ranked_combined),
    }


def award_certifications(chart_type: str):
    """Award Ngoma certifications based on cumulative points."""
    from django.db.models import Sum
    thresholds = Certification.THRESHOLDS

    releases = Release.objects.filter(chart_type=chart_type)
    for release in releases:
        total = MonthlyChartEntry.objects.filter(
            release=release, platform__isnull=True
        ).aggregate(total=Sum('total_points'))['total'] or 0

        for level, threshold in sorted(thresholds.items(), key=lambda x: x[1]):
            if total >= threshold:
                Certification.objects.get_or_create(
                    release=release, level=level,
                    defaults={'total_points': total}
                )
