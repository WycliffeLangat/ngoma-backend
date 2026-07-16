"""
Data cleaning and processing pipeline for Ngoma Charts.
Converts raw xlsx weekly data into normalized chart entries.
"""
import re
import openpyxl
from collections import defaultdict, Counter
from django.db import transaction
from .artist_credits import format_artist_list, parse_artist_credit, should_preserve_registered_artist_name
from .methodology import (
    PUBLIC_CHART_LIMIT,
    WEEKLY_CHART_LIMIT,
    platform_max_for,
    platforms_for,
    public_points,
    weekly_points,
)
from .models import (
    Platform, Artist, Release, WeeklyUpload, MonthlyChart,
    PlatformChartEntry, MonthlyChartEntry, NormalizationRule,
    ReleaseArtistCredit, ChartType
)
from .special_artist_rules import clean_vestine_dorcas_credit_names


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


def _preserve_artist_name(name):
    artist = Artist.objects.filter(name__iexact=name).first()
    return should_preserve_registered_artist_name(name, artist)


def parsed_artist_names(artist_credit):
    return parse_artist_credit(
        artist_credit,
        preserve_name=_preserve_artist_name(artist_credit),
    )


def _sync_release_credits(release, primary_names, featured_names):
    primary_names, featured_names = clean_vestine_dorcas_credit_names(
        release.canonical_title or release.title,
        primary_names,
        featured_names,
    )
    desired_primary = [get_or_create_artist(name) for name in primary_names]
    desired_featured = [get_or_create_artist(name) for name in featured_names]
    existing = list(release.artist_credits.select_related('artist'))

    primary_artists = list(desired_primary)
    desired_primary_ids = {artist.id for artist in desired_primary}
    parsed_collaboration = len(desired_primary) > 1 or bool(desired_featured)
    for credit in existing:
        if credit.role != 'primary' or credit.artist_id in desired_primary_ids:
            continue
        # Migration 0009 may have stored the entire collaboration string as
        # one pseudo-artist. Replace that generated row with real members.
        if parsed_collaboration and credit.artist_id == release.artist_id:
            continue
        primary_artists.append(credit.artist)

    primary_ids = {artist.id for artist in primary_artists}
    featured_artists = [
        artist for artist in desired_featured
        if artist.id not in primary_ids
    ]
    featured_ids = {artist.id for artist in featured_artists}
    for credit in existing:
        if (
            credit.role == 'featured'
            and credit.artist_id not in primary_ids
            and credit.artist_id not in featured_ids
        ):
            featured_artists.append(credit.artist)
            featured_ids.add(credit.artist_id)

    release.artist_credits.all().delete()
    ReleaseArtistCredit.objects.bulk_create([
        *[
            ReleaseArtistCredit(
                release=release,
                artist=artist,
                role='primary',
                position=position,
            )
            for position, artist in enumerate(primary_artists)
        ],
        *[
            ReleaseArtistCredit(
                release=release,
                artist=artist,
                role='featured',
                position=position,
            )
            for position, artist in enumerate(featured_artists)
        ],
    ])

    featured_credit = format_artist_list(artist.name for artist in featured_artists)
    if featured_credit and release.featured_artists != featured_credit:
        release.featured_artists = featured_credit
        release.save(update_fields=['featured_artists', 'updated_at'])


def get_or_create_release(title, artist_credit, chart_type):
    primary_names, featured_names = parsed_artist_names(artist_credit)
    if not primary_names:
        primary_names = [artist_credit or 'Unknown Artist']
    primary_names, featured_names = clean_vestine_dorcas_credit_names(
        title,
        primary_names,
        featured_names,
    )
    artist_obj = get_or_create_artist(primary_names[0])
    canonical = title.lower().strip()
    try:
        release = Release.objects.get(
            canonical_title=canonical,
            artist=artist_obj,
            chart_type=chart_type,
        )
    except Release.DoesNotExist:
        release = Release.objects.create(
            title=title, artist=artist_obj, chart_type=chart_type,
            canonical_title=canonical
        )
    _sync_release_credits(release, primary_names, featured_names)
    return release


@transaction.atomic
def process_weekly_upload(upload: WeeklyUpload, file_obj=None, harmonize=True) -> dict:
    """
    Process a weekly xlsx upload:
    1. Parse the file
    2. Normalize all entries
    3. Deduplicate within week/platform
    4. Save PlatformChartEntry records
    5. Rebuild MonthlyChartEntry aggregates for this month

    harmonize=False skips the chart-type-wide harmonize_chart_history call
    (still rebuilds this month's own MonthlyChartEntry rows). Callers doing
    several uploads back-to-back — e.g. multiple weeks in a row — should
    pass False and harmonize once at the end; harmonize_chart_history always
    recomputes every published month of the chart type, so running it after
    every single upload is redundant and, over HTTP, can exceed platform
    request-timeout limits that this app has no control over.
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
    platform_names = platforms_for(upload.chart_type)

    platforms = {p.name: p for p in Platform.objects.filter(name__in=platform_names)}
    platform_col = {h: i for i, h in enumerate(headers)}
    recognized = [name for name in platform_names if name in platform_col]
    if not recognized:
        expected = ', '.join(platform_names)
        raise ValueError(f'No supported platform columns found. Expected one or more of: {expected}.')
    configured = [name for name in recognized if name in platforms]
    if not configured:
        raise ValueError('The workbook columns are valid, but the matching platforms are not configured.')

    # Capture the releases supported by the previous version before clearing
    # its rows. A corrected re-upload can resolve to completely different
    # title/artist pairs; without this list, the bad version's releases linger
    # forever as unsupported CMS records.
    previous_release_ids = list(
        PlatformChartEntry.objects.filter(upload=upload)
        .values_list('release_id', flat=True).distinct()
    )
    PlatformChartEntry.objects.filter(upload=upload).delete()

    total_processed = 0
    total_dupes = 0
    release_cache = {}
    platform_entries_to_create = []

    for plat_name in platform_names:
        if plat_name not in platform_col or plat_name not in platforms:
            continue
        plat = platforms[plat_name]
        col_i = platform_col[plat_name]

        week_entries = []
        for pos, row in enumerate(data_rows[:WEEKLY_CHART_LIMIT], start=1):
            cell = row[col_i] if col_i < len(row) else None
            if cell and str(cell).strip():
                raw = str(cell).strip()
                title_raw, artist_raw = split_song_artist(raw, is_album)
                points = weekly_points(pos)
                canon_title, canon_artist, key = normalize_entry(
                    title_raw, artist_raw, artist_rules, title_rules, is_album
                )
                primary_names, featured_names = parsed_artist_names(canon_artist)
                credit_key = tuple(sorted(
                    name.casefold() for name in [*primary_names, *featured_names]
                ))
                canonical_key = (key[0], credit_key or (key[1],))
                week_entries.append((
                    canonical_key, canon_title, canon_artist, points,
                    pos, title_raw, artist_raw,
                ))

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
            release_key = (
                ct.casefold().strip(),
                ca.casefold().strip(),
                upload.chart_type,
            )
            release_obj = release_cache.get(release_key)
            if release_obj is None:
                release_obj = get_or_create_release(ct, ca, upload.chart_type)
                release_cache[release_key] = release_obj
            platform_entries_to_create.append(PlatformChartEntry(
                upload=upload, platform=plat, release=release_obj,
                position=pos, points=pts, raw_title=rt, raw_artist=ra
            ))
            total_processed += 1

    if platform_entries_to_create:
        PlatformChartEntry.objects.bulk_create(
            platform_entries_to_create,
            batch_size=500,
        )

    upload.processed = True
    upload.duplicates_dropped = total_dupes
    upload.entries_processed = total_processed
    upload.save()

    # Rebuild monthly aggregates
    result = rebuild_monthly_chart(upload.chart_type, upload.year, upload.month, harmonize=harmonize)
    if previous_release_ids:
        # Local import avoids pipeline <-> cms_utils import-time circularity.
        from .cms_utils import prune_orphaned_releases
        result['orphaned_releases_pruned'] = prune_orphaned_releases(
            previous_release_ids
        )
    result['dupes_dropped'] = total_dupes
    result['entries_processed'] = total_processed
    return result


@transaction.atomic
def rebuild_monthly_chart(
    chart_type: str,
    year: int,
    month: int,
    *,
    harmonize=True,
) -> dict:
    """
    Aggregate all weekly uploads for a month into MonthlyChartEntry records.
    """
    import calendar
    uploads = WeeklyUpload.objects.filter(
        chart_type=chart_type, year=year, month=month, processed=True
    )
    if not uploads.exists():
        return {'error': 'No processed uploads for this period'}

    platform_names = platforms_for(chart_type)

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
        entries = PlatformChartEntry.objects.filter(
            upload=upload,
            position__gte=1,
            position__lte=WEEKLY_CHART_LIMIT,
        ).select_related('release', 'platform')
        releases_seen_this_week = set()
        for e in entries:
            pn = e.platform.name
            if pn not in platform_agg:
                continue
            rid = e.release.id
            points = weekly_points(e.position)
            if not points:
                continue
            platform_agg[pn][rid]['pts'] += points
            platform_agg[pn][rid]['wks'] += 1
            if e.position < platform_agg[pn][rid]['peak']:
                platform_agg[pn][rid]['peak'] = e.position
            combined_agg[rid]['pts'] += points
            combined_agg[rid]['plats'].add(pn)
            if e.position < combined_agg[rid]['peak']:
                combined_agg[rid]['peak'] = e.position
            if rid not in releases_seen_this_week:
                combined_agg[rid]['wks'] += 1
                releases_seen_this_week.add(rid)

    entries_to_create = []

    # Create platform entries
    for pn, plat in platforms.items():
        ranked = sorted(
            platform_agg[pn].items(),
            key=lambda item: (-item[1]['pts'], item[0]),
        )
        for rank, (rid, data) in enumerate(ranked, 1):
            entries_to_create.append(MonthlyChartEntry(
                chart=chart, platform=plat, release_id=rid,
                rank=rank,
                total_points=public_points(rank),
                raw_total_points=data['pts'],
                weeks_on_chart=data['wks'], platform_count=1,
                platform_max=1,
                peak_rank=min(rank, PUBLIC_CHART_LIMIT),
            ))

    # Create combined entries
    ranked_combined = sorted(
        combined_agg.items(),
        key=lambda item: (-item[1]['pts'], -len(item[1]['plats']), item[0]),
    )
    for rank, (rid, data) in enumerate(ranked_combined, 1):
        entries_to_create.append(MonthlyChartEntry(
            chart=chart, platform=None, release_id=rid,
            rank=rank,
            total_points=public_points(rank),
            raw_total_points=data['pts'],
            weeks_on_chart=data['wks'],
            platform_count=len(data['plats']),
            platform_max=platform_max_for(chart_type),
            peak_rank=min(rank, PUBLIC_CHART_LIMIT),
        ))

    MonthlyChartEntry.objects.bulk_create(entries_to_create, batch_size=500)

    # Rebuild every dependent field, including downstream months whose
    # movement/peak values depend on this month.
    harmonization = None
    if harmonize:
        from .cms_utils import harmonize_chart_history
        harmonization = harmonize_chart_history(chart_ids=[chart.id])

    return {
        'chart': str(chart),
        'platform_entries': sum(len(platform_agg[p]) for p in platform_names),
        'combined_entries': len(ranked_combined),
        'harmonization': harmonization,
    }


def award_certifications(chart_type: str):
    """Compatibility wrapper for canonical published Top 50 certification."""
    from .cms_utils import recalculate_certifications
    return recalculate_certifications(chart_type=chart_type)
