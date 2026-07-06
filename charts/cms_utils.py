import csv
import io
import re
from collections import Counter, defaultdict
from django.db import transaction
from django.db.models import Q
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from django.utils import timezone
from django.utils.text import slugify
import openpyxl
from .artist_credits import format_artist_list, parse_artist_credit, split_artist_names, release_credit_payload
from .methodology import (
    PUBLIC_CHART_LIMIT,
    REGIONAL_CHART_CODES,
    is_public_status,
    platform_max_for,
    public_points,
)
from .models import AuditLog, Artist, Release, MonthlyChart, MonthlyChartEntry, PlatformChartEntry, RegionalChartEntry, Platform, ChartType, CertificationRule, Certification, SiteSetting, NormalizationRule


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


def published_top50_entries():
    """Canonical queryset for public statistics and historical records.

    Every aggregate must use this foundation so drafts, rejected charts,
    platform rows and ranks below the published Top 50 cannot silently alter
    public totals.
    """
    return MonthlyChartEntry.objects.filter(
        chart__is_published=True,
        chart__status='published',
        platform__isnull=True,
        rank__gte=1,
        rank__lte=50,
    )


def published_artist_entries(artist):
    return published_top50_entries().filter(
        Q(release__artist_credits__artist=artist)
        | Q(release__artist=artist, release__artist_credits__isnull=True)
    ).distinct()


def client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def json_safe(value):
    """Recursively normalize serializer/model values before storing an audit JSON snapshot."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, 'name') and value.__class__.__name__ in {'FieldFile', 'ImageFieldFile'}:
        return value.name or ''
    if hasattr(value, 'pk'):
        return value.pk
    return str(value)


def audit(request, action, module='', obj=None, old=None, new=None, reason=''):
    try:
        AuditLog.objects.create(
            action=action,
            module=module,
            object_type=obj.__class__.__name__ if obj else '',
            object_id=str(getattr(obj, 'pk', '') or ''),
            object_repr=str(obj)[:255] if obj else '',
            old_value=json_safe(old or {}),
            new_value=json_safe(new or {}),
            reason=reason or '',
            user=request.user if request and request.user.is_authenticated else None,
            ip_address=client_ip(request) if request else None,
            user_agent=(request.META.get('HTTP_USER_AGENT', '') if request else '')[:2000],
        )
    except Exception:
        pass

    # Any CMS action that can affect the public website must move the public
    # revision forward. The public frontend watches this lightweight revision
    # and reloads/refetches, so CMS edits become visible without rebuilding
    # the frontend or regenerating static chart-data files.
    if module in PUBLIC_DATA_AUDIT_MODULES:
        bump_public_revision()


def cms_exception_handler(exc, context):
    """
    Custom DRF exception handler.  Wraps the default handler so that any
    exception — not just APIException subclasses — always returns a JSON
    response instead of letting Django's 500 handler return HTML.
    """
    import logging
    from rest_framework.views import exception_handler
    from rest_framework.response import Response

    response = exception_handler(exc, context)
    if response is not None:
        return response

    logger = logging.getLogger('django.request')
    logger.exception('Unhandled exception in CMS view: %s', exc)

    detail = str(exc) if str(exc) else type(exc).__name__
    return Response({'detail': detail}, status=500)


def bump_public_revision():
    """
    Guarantee that _public_data_revision() returns a different string after
    any merge or hard-delete, even if audit() silently failed and no model's
    updated_at changed (e.g. the deleted record wasn't the most recently
    touched one).  Writes a timestamp to a dedicated SiteSetting row that
    app_data._public_data_revision() includes in its hash.
    """
    try:
        SiteSetting.objects.update_or_create(
            key='_cms_action_revision',
            defaults={'value': {'ts': timezone.now().isoformat()}},
        )
    except Exception:
        pass


def normalize_name(value):
    return re.sub(r'\s+', ' ', str(value or '').strip())


def record_merge_normalization(rule_type, raw_value, canonical_value, notes=''):
    """
    Auto-create/repoint a NormalizationRule so future ingested rows matching a
    just-merged duplicate's raw name/title resolve to the surviving record
    instead of recreating it (see charts/pipeline.py get_norm_rules()/
    normalize_entry()).
    """
    raw_value = (raw_value or '').strip()
    canonical_value = (canonical_value or '').strip()
    if not raw_value or not canonical_value or raw_value.lower() == canonical_value.lower():
        return
    NormalizationRule.objects.update_or_create(
        rule_type=rule_type, raw_value=raw_value,
        defaults={'canonical_value': canonical_value, 'notes': notes},
    )
    # Chained merges: repoint any rule that already pointed at the name/title
    # that just got merged away, so it keeps resolving to the final survivor.
    NormalizationRule.objects.filter(rule_type=rule_type, canonical_value=raw_value).update(
        canonical_value=canonical_value
    )


def prune_orphaned_releases(release_ids):
    """
    Delete releases from `release_ids` that no longer have any supporting
    chart data (no PlatformChartEntry, no MonthlyChartEntry) — leftover
    "ghost" rows from a deleted weekly upload or chart period that would
    otherwise keep surfacing in release listings and duplicate detection.
    Only ever considers releases actually touched by the caller's delete —
    never a blanket sweep — so a manually-added, not-yet-charted release is
    never at risk.
    """
    release_ids = [rid for rid in set(release_ids or []) if rid]
    if not release_ids:
        return 0
    orphan_ids = [
        rid for rid in release_ids
        if not PlatformChartEntry.objects.filter(release_id=rid).exists()
        and not MonthlyChartEntry.objects.filter(release_id=rid).exists()
    ]
    if orphan_ids:
        Release.objects.filter(pk__in=orphan_ids).delete()
    return len(orphan_ids)


def unique_slug(model, text, field='slug'):
    base = slugify(text)[:80] or 'item'
    slug = base
    i = 2
    while model.objects.filter(**{field: slug}).exists():
        slug = f'{base}-{i}'[:100]
        i += 1
    return slug


def parse_chart_file(file_obj):
    filename = getattr(file_obj, 'name', '') or ''
    ext = filename.lower().split('.')[-1]
    rows = []
    if ext in {'xlsx', 'xlsm', 'xltx', 'xltm'}:
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        ws = wb.active
        values = list(ws.iter_rows(values_only=True))
        if not values:
            return []
        headers = [normalize_header(h) for h in values[0]]
        for raw in values[1:]:
            if not any(cell not in (None, '') for cell in raw):
                continue
            rows.append({headers[i] if i < len(headers) else f'col_{i+1}': raw[i] for i in range(len(raw))})
    else:
        content = file_obj.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            rows.append({normalize_header(k): v for k, v in row.items()})
    return [coerce_chart_row(r, i + 1) for i, r in enumerate(rows)]


def normalize_header(value):
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')


def pick(row, *keys):
    for key in keys:
        k = normalize_header(key)
        if k in row and row[k] not in (None, ''):
            return row[k]
    return ''


def split_title_artist(value):
    raw = normalize_name(value)
    if ' - ' in raw:
        title, artist = raw.split(' - ', 1)
        return normalize_name(title), normalize_name(artist)
    return raw, ''


def as_int(value, default=None):
    if value in (None, ''):
        return default
    try:
        return int(float(str(value).replace(',', '').strip()))
    except Exception:
        return default


def coerce_chart_row(row, row_number):
    combined = pick(row, 'entry', 'song', 'album', 'release', 'title_artist', 'title - artist')
    title = normalize_name(pick(row, 'title', 'song_title', 'album_title', 'release_title'))
    artist = normalize_name(pick(row, 'artist', 'main_artist', 'primary_artist'))
    if (not title or not artist) and combined:
        split_title, split_artist = split_title_artist(combined)
        title = title or split_title
        artist = artist or split_artist
    rank = as_int(pick(row, 'rank', '#', 'position', 'pos', 'r'), row_number)
    points = as_int(pick(row, 'points', 'total_points', 'pts', 'raw_points', 'rp'), None)
    return {
        'row_number': row_number,
        'rank': rank,
        'title': title,
        'artist': artist,
        'featured_artists': normalize_name(pick(row, 'featured_artists', 'features', 'feat', 'fa')),
        'credited_artists': normalize_name(pick(row, 'credited_artists', 'credits')),
        'country': normalize_name(pick(row, 'country')),
        'country_code': normalize_name(pick(row, 'country_code', 'cc'))[:2].upper(),
        'release_year': as_int(pick(row, 'release_year', 'year', 'y'), None),
        'total_points': points,
        'platform_count': as_int(pick(row, 'platform_count', 'platforms', 'entries'), None),
        'weeks_on_chart': as_int(pick(row, 'weeks_on_chart', 'weeks', 'months', 'w'), 1),
        'peak_rank': as_int(pick(row, 'peak', 'peak_rank'), rank),
        'prev_rank': as_int(pick(row, 'last_month', 'prev', 'prev_rank', 'lm'), None),
        'isrc': normalize_name(pick(row, 'isrc')),
        'upc': normalize_name(pick(row, 'upc')),
        'genre': normalize_name(pick(row, 'genre')),
        'label': normalize_name(pick(row, 'label')),
        'distributor': normalize_name(pick(row, 'distributor')),
        'raw': {str(k): '' if v is None else str(v) for k, v in row.items()},
    }


def validate_chart_rows(rows, chart_type='singles', platform=None, max_size=None, year=None, month=None):
    errors, warnings = [], []
    max_size = max_size or (platform.max_chart_size if platform else 50)
    ranks = [r.get('rank') for r in rows if r.get('rank')]
    rank_counts = Counter(ranks)
    keys = Counter((r.get('title', '').lower(), r.get('artist', '').lower()) for r in rows if r.get('title') and r.get('artist'))

    for row in rows:
        rn = row.get('row_number')
        if not row.get('title'):
            errors.append({'row': rn, 'field': 'title', 'message': 'Missing release title'})
        if not row.get('artist'):
            errors.append({'row': rn, 'field': 'artist', 'message': 'Missing main artist'})
        if not row.get('rank'):
            errors.append({'row': rn, 'field': 'rank', 'message': 'Missing rank'})
        if row.get('rank') and row['rank'] > max_size:
            warnings.append({'row': rn, 'field': 'rank', 'message': f'Rank is outside Top {max_size}'})
        if not row.get('country_code') and not row.get('country'):
            warnings.append({'row': rn, 'field': 'country', 'message': 'Missing artist/release country'})
        if not row.get('release_year'):
            warnings.append({'row': rn, 'field': 'release_year', 'message': 'Missing release year'})
        if keys[(row.get('title', '').lower(), row.get('artist', '').lower())] > 1:
            warnings.append({'row': rn, 'field': 'duplicate', 'message': 'Possible duplicate release in upload'})
        if row.get('rank') and rank_counts[row['rank']] > 1:
            errors.append({'row': rn, 'field': 'rank', 'message': f'Duplicate rank #{row["rank"]}'})
        if platform and row.get('total_points') is not None:
            expected = max_size - int(row.get('rank') or 0) + 1
            if expected > 0 and int(row['total_points']) != expected:
                warnings.append({'row': rn, 'field': 'total_points', 'message': f'Points mismatch. Expected {expected} for platform Top {max_size}'})

    if ranks:
        missing = [rank for rank in range(1, min(max_size, max(ranks)) + 1) if rank not in rank_counts]
        if missing:
            warnings.append({'row': None, 'field': 'rank', 'message': f'Missing rank(s): {missing[:15]}{"..." if len(missing)>15 else ""}'})
    for row in rows:
        row['entry_status'] = detect_entry_status(row, chart_type, platform, year, month)
    return {
        'errors': errors,
        'warnings': warnings,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'row_count': len(rows),
        'max_size': max_size,
        'can_publish': len(errors) == 0 and len(rows) > 0,
    }


def find_artist_by_name(name):
    if not name:
        return None
    exact = Artist.objects.filter(name__iexact=name).first()
    if exact:
        return exact
    try:
        return Artist.objects.filter(aliases__contains=[name]).first()
    except Exception:
        for artist in Artist.objects.exclude(aliases=[]).only('id', 'aliases'):
            if name in (artist.aliases or []):
                return artist
        return None


def get_or_create_cms_artist(name, country='', country_code=''):
    name = normalize_name(name)
    artist = find_artist_by_name(name)
    if artist:
        changed = False
        if country and not artist.country:
            artist.country = country; changed = True
        if country_code and not artist.country_code:
            artist.country_code = country_code; changed = True
        if changed:
            artist.save(update_fields=['country', 'country_code', 'updated_at'])
        return artist
    return Artist.objects.create(name=name, slug=unique_slug(Artist, name), country=country or '', country_code=(country_code or '')[:2].upper())


def get_or_create_cms_release(row, artist, chart_type):
    preserve_name = bool(
        artist
        and artist.name.casefold() == normalize_name(row.get('artist')).casefold()
        and artist.artist_type in {'group', 'band', 'duo'}
    )
    primary_names, parsed_featured_names = parse_artist_credit(
        row.get('artist'),
        preserve_name=preserve_name,
    )
    primary_names = primary_names or [artist.name]
    explicit_featured = split_artist_names(row.get('featured_artists'))
    featured_names = []
    seen_featured = set()
    primary_keys = {name.casefold() for name in primary_names}
    for name in [*parsed_featured_names, *explicit_featured]:
        key = name.casefold()
        if key not in primary_keys and key not in seen_featured:
            featured_names.append(name)
            seen_featured.add(key)

    artist = get_or_create_cms_artist(
        primary_names[0],
        row.get('country'),
        row.get('country_code'),
    )
    canonical = normalize_name(row.get('title')).lower()
    release, created = Release.objects.get_or_create(
        canonical_title=canonical,
        artist=artist,
        chart_type=chart_type,
        defaults={'title': row.get('title') or '', 'country': row.get('country') or artist.country, 'country_code': row.get('country_code') or artist.country_code},
    )
    fields = []
    for attr in ['featured_artists', 'credited_artists', 'release_year', 'isrc', 'upc', 'genre', 'label', 'distributor']:
        value = row.get(attr)
        if value not in (None, '') and getattr(release, attr, None) in (None, ''):
            setattr(release, attr, value)
            fields.append(attr)
    if fields:
        release.save(update_fields=fields + ['updated_at'])
    primary_artists = [
        get_or_create_cms_artist(
            name,
            row.get('country') if position == 0 else '',
            row.get('country_code') if position == 0 else '',
        )
        for position, name in enumerate(primary_names)
    ]
    featured_artists = [get_or_create_cms_artist(name) for name in featured_names]
    from .pipeline import _sync_release_credits
    _sync_release_credits(
        release,
        [credit_artist.name for credit_artist in primary_artists],
        [credit_artist.name for credit_artist in featured_artists],
    )
    featured_credit = format_artist_list(
        credit_artist.display_name or credit_artist.name
        for credit_artist in featured_artists
    )
    if featured_credit and release.featured_artists != featured_credit:
        release.featured_artists = featured_credit
        release.save(update_fields=['featured_artists', 'updated_at'])
    return release


def detect_entry_status(row, chart_type, platform, year, month):
    if not (year and month and row.get('title') and row.get('artist')):
        return 'unknown'
    raw_artist = normalize_name(row.get('artist'))
    exact_artist = find_artist_by_name(raw_artist)
    preserve_name = bool(
        exact_artist and exact_artist.artist_type in {'group', 'band', 'duo'}
    )
    primary_names, _ = parse_artist_credit(raw_artist, preserve_name=preserve_name)
    artist = find_artist_by_name(primary_names[0] if primary_names else raw_artist)
    if not artist:
        return 'new'
    release = Release.objects.filter(canonical_title=normalize_name(row.get('title')).lower(), artist=artist, chart_type=chart_type).first()
    if not release:
        return 'new'
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    previous = MonthlyChartEntry.objects.filter(chart__year=prev_year, chart__month=prev_month, chart__chart_type=chart_type, release=release, platform=platform).first()
    if previous:
        row['prev_rank'] = previous.rank
        return 'returning'
    earlier = MonthlyChartEntry.objects.filter(chart__chart_type=chart_type, release=release, platform=platform).exclude(chart__year=year, chart__month=month).exists()
    return 'reentry' if earlier else 'new'


def publish_chart_upload(upload, user=None):
    platform = upload.platform
    chart, _ = MonthlyChart.objects.get_or_create(
        year=upload.year,
        month=upload.month,
        chart_type=upload.chart_type,
        defaults={'is_published': False, 'status': 'draft'},
    )
    MonthlyChartEntry.objects.filter(chart=chart, platform=platform).delete()
    entries = []
    for row in sorted(upload.rows_data or [], key=lambda r: int(r.get('rank') or 9999)):
        raw_artist = normalize_name(row.get('artist'))
        existing_artist = find_artist_by_name(raw_artist)
        preserve_name = bool(
            existing_artist
            and existing_artist.artist_type in {'group', 'band', 'duo'}
        )
        primary_names, _ = parse_artist_credit(raw_artist, preserve_name=preserve_name)
        artist = get_or_create_cms_artist(
            primary_names[0] if primary_names else raw_artist,
            row.get('country'),
            row.get('country_code'),
        )
        release = get_or_create_cms_release(row, artist, upload.chart_type)
        rank = int(row.get('rank') or len(entries) + 1)
        raw_points = row.get('total_points')
        if raw_points is None:
            raw_points = public_points(rank)
        entries.append(MonthlyChartEntry(
            chart=chart,
            platform=platform,
            release=release,
            rank=rank,
            total_points=public_points(rank),
            raw_total_points=max(int(raw_points or 0), 0),
            weeks_on_chart=int(row.get('weeks_on_chart') or 1),
            platform_count=int(row.get('platform_count') or (1 if platform else 0)),
            platform_max=1 if platform else platform_max_for(upload.chart_type),
            peak_rank=int(row.get('peak_rank') or row.get('rank') or 1),
            prev_rank=row.get('prev_rank') or None,
        ))
    MonthlyChartEntry.objects.bulk_create(entries, batch_size=500)
    chart.is_published = True
    chart.status = 'published'
    chart.published_at = timezone.now()
    chart.published_by = user
    chart.save(update_fields=['is_published', 'status', 'published_at', 'published_by', 'updated_at'])
    upload.status = 'published'
    upload.published_by = user
    upload.published_at = timezone.now()
    upload.save(update_fields=['status', 'published_by', 'published_at', 'updated_at'])
    harmonize_chart_history(chart_ids=[chart.id])
    return chart, len(entries)


def certification_thresholds():
    rules = CertificationRule.objects.filter(active=True)
    if rules.exists():
        return {r.level: r.threshold for r in rules}
    return Certification.THRESHOLDS


def recalculate_certifications(chart_type=None, release=None):
    from django.db.models import Sum

    published = published_top50_entries()
    existing_certifications = Certification.objects.all()
    if chart_type:
        published = published.filter(chart__chart_type=chart_type)
        existing_certifications = existing_certifications.filter(
            release__chart_type=chart_type
        )
    if release:
        published = published.filter(release=release)
        existing_certifications = existing_certifications.filter(
            release=release
        )
    thresholds = certification_thresholds()
    release_ids = set(
        published.values_list('release_id', flat=True).distinct()
    )
    release_ids.update(
        existing_certifications.values_list('release_id', flat=True).distinct()
    )
    if release:
        release_ids.add(release.pk)
    release_ids = sorted(release_ids)
    totals = {
        row['release_id']: row['total']
        for row in (
            published
            .filter(release_id__in=release_ids)
            .values('release_id')
            .annotate(total=Sum('total_points'))
        )
    }
    certifications_by_release = defaultdict(dict)
    for item in Certification.objects.filter(release_id__in=release_ids):
        certifications_by_release[item.release_id][item.level] = item

    updated = 0
    for release_id in release_ids:
        total = totals.get(release_id, 0) or 0
        achieved = {
            level
            for level, threshold in thresholds.items()
            if total >= threshold
        }
        existing = certifications_by_release[release_id]

        # Official awards are historical editorial records and are never
        # silently removed. Their points still follow the live chart totals.
        # Non-official, automatically-created awards are removed when a chart
        # correction takes the release back below the applicable threshold.
        for level, item in existing.items():
            if level not in achieved and not item.is_official:
                item.delete()
                updated += 1
                continue
            if item.total_points != total:
                item.total_points = total
                item.save(update_fields=['total_points'])
                updated += 1

        for level in achieved:
            if level not in existing:
                Certification.objects.create(
                    release_id=release_id,
                    level=level,
                    total_points=total,
                )
                updated += 1
    return updated


def _previous_period(year, month):
    return (year, month - 1) if month > 1 else (year - 1, 12)


def entry_is_public(entry):
    """Same visibility rule app_data._chart_data() uses to decide whether an
    entry appears in the public payload — release and its (FK) artist must
    both be in a public-facing status. Used at ranking time so a hidden
    release never occupies a public 1-50 slot; see entry_is_public's call
    site in harmonize_chart_history."""
    return is_public_status(entry.release.status) and is_public_status(entry.release.artist.status)


def resolve_release_country_code(release):
    """Single source of truth for chart-eligibility country resolution.

    Mirrors the "artist country is authoritative" display rule in
    app_data.py: the primary credited artist's country wins over a release's
    own (possibly stale) country field.
    """
    credits = release_credit_payload(release)
    artist = credits["primary_artists"][0] if credits["primary_artists"] else release.artist
    return (artist.country_code or release.country_code or "").strip().upper()


def aggregate_platform_entries(chart_ids):
    """Aggregate per-platform (platform IS NOT NULL) MonthlyChartEntry rows by
    (chart, release): summed raw points across platforms, distinct platform
    count, and max weeks-on-chart — the same shape as the Combined scope's
    own fields.

    Per-platform rows are the one scope publish validation never requires
    trimming, so they're the reliable full candidate pool for anything that
    needs "every release that actually charted that month, not just the
    public Top 50" — both the Combined self-heal and the regional sync use
    this.

    Returns {(chart_id, release_id): {'source': MonthlyChartEntry, ...}}.
    """
    candidates = {}
    platform_entries = (
        MonthlyChartEntry.objects.filter(
            chart_id__in=chart_ids, platform__isnull=False
        )
        .select_related('chart', 'release', 'release__artist')
        .prefetch_related('release__artist_credits__artist')
    )
    for entry in platform_entries:
        key = (entry.chart_id, entry.release_id)
        candidate = candidates.setdefault(key, {
            'source': entry,
            'raw_total_points': 0,
            'platform_ids': set(),
            'weeks_on_chart': 0,
        })
        candidate['raw_total_points'] += max(int(entry.raw_total_points or 0), 0)
        candidate['platform_ids'].add(entry.platform_id)
        candidate['weeks_on_chart'] = max(
            candidate['weeks_on_chart'],
            int(entry.weeks_on_chart or 0),
        )
    return candidates


def sync_combined_chart_entries(charts):
    """Ensure the Combined (platform IS NULL) scope has a row for every
    release present in the per-platform aggregate for that chart.

    Storage is never trimmed to the public Top 50 — only the public API's
    own rank<=50 filter limits what's shown there. This restores whatever a
    prior manual trim deleted and keeps every future rebuild/publish from
    ever needing one: it's additive only, never deletes a Combined row.
    """
    chart_ids = [chart.id for chart in charts]
    candidates = aggregate_platform_entries(chart_ids)

    existing_release_ids_by_chart = defaultdict(set)
    for chart_id, release_id in MonthlyChartEntry.objects.filter(
        chart_id__in=chart_ids, platform__isnull=True
    ).values_list('chart_id', 'release_id'):
        existing_release_ids_by_chart[chart_id].add(release_id)

    to_create = []
    for (chart_id, release_id), candidate in candidates.items():
        if release_id in existing_release_ids_by_chart[chart_id]:
            continue
        source = candidate['source']
        to_create.append(MonthlyChartEntry(
            chart_id=chart_id,
            platform=None,
            release_id=release_id,
            # Temporary unique placeholder; the main harmonize ranking loop
            # (which runs right after this) assigns the real rank.
            rank=-(3_000_000 + release_id),
            total_points=0,
            raw_total_points=candidate['raw_total_points'],
            weeks_on_chart=candidate['weeks_on_chart'],
            platform_count=len(candidate['platform_ids']),
            platform_max=platform_max_for(source.chart.chart_type),
            peak_rank=1_000_000,
        ))
    if to_create:
        MonthlyChartEntry.objects.bulk_create(to_create, batch_size=500)
    return {'restored': len(to_create)}


def sync_regional_chart_entries(charts):
    """Rebuild RegionalChartEntry rows from full per-platform monthly rows.

    Country-scoped charts are independent aggregates, just like Combined:
    their raw score and candidate pool come from all per-platform rows, never
    from the already-ranked global Combined Top 50.

    Creates rows for newly-eligible releases, deletes rows for releases that
    are no longer eligible, and keeps raw points and display metadata
    synchronized. Rank assignment happens afterward.
    """
    if not REGIONAL_CHART_CODES:
        return {'created': 0, 'updated': 0, 'removed': 0}

    chart_ids = [chart.id for chart in charts]
    platform_candidates = aggregate_platform_entries(chart_ids)

    candidate_entries = []
    for candidate in platform_candidates.values():
        source = candidate['source']
        source.raw_total_points = candidate['raw_total_points']
        source.platform_count = len(candidate['platform_ids'])
        source.platform_max = platform_max_for(source.chart.chart_type)
        source.weeks_on_chart = candidate['weeks_on_chart']
        candidate_entries.append(source)

    existing = {
        (entry.chart_id, entry.region, entry.release_id): entry
        for entry in RegionalChartEntry.objects.filter(
            chart_id__in=chart_ids, region__in=REGIONAL_CHART_CODES
        )
    }

    seen_keys = set()
    to_create = []
    to_update = []
    synced_fields = (
        'raw_total_points', 'weeks_on_chart', 'platform_count',
        'platform_max', 'release_year', 'confidence', 'featured_artists',
    )
    for entry in candidate_entries:
        code = resolve_release_country_code(entry.release)
        if code not in REGIONAL_CHART_CODES:
            continue
        key = (entry.chart_id, code, entry.release_id)
        seen_keys.add(key)
        existing_row = existing.get(key)
        if existing_row:
            changed = False
            for field in synced_fields:
                value = getattr(entry, field)
                if getattr(existing_row, field) != value:
                    setattr(existing_row, field, value)
                    changed = True
            if changed:
                to_update.append(existing_row)
        else:
            to_create.append(RegionalChartEntry(
                chart_id=entry.chart_id,
                region=code,
                release_id=entry.release_id,
                # Temporary unique placeholder; harmonize_regional_chart_entries
                # assigns the real rank right after this runs.
                rank=-(1_000_000 + entry.release_id),
                total_points=0,
                raw_total_points=entry.raw_total_points,
                weeks_on_chart=entry.weeks_on_chart,
                platform_count=entry.platform_count,
                platform_max=entry.platform_max,
                release_year=entry.release_year,
                confidence=entry.confidence,
                featured_artists=entry.featured_artists,
                peak_rank=1_000_000,
            ))

    stale_ids = [row.id for key, row in existing.items() if key not in seen_keys]
    if stale_ids:
        RegionalChartEntry.objects.filter(id__in=stale_ids).delete()
    if to_update:
        RegionalChartEntry.objects.bulk_update(to_update, list(synced_fields))
    if to_create:
        RegionalChartEntry.objects.bulk_create(to_create, batch_size=500)

    return {'created': len(to_create), 'updated': len(to_update), 'removed': len(stale_ids)}


def harmonize_regional_chart_entries(charts):
    """Re-rank RegionalChartEntry rows per (chart, region) scope.

    Direct port of the per-scope ranking + history block in
    harmonize_chart_history, targeting RegionalChartEntry/region instead of
    MonthlyChartEntry/platform.
    """
    chart_ids = [chart.id for chart in charts]
    entries = list(
        RegionalChartEntry.objects.filter(chart_id__in=chart_ids, region__in=REGIONAL_CHART_CODES)
        .select_related('chart', 'release', 'release__artist')
    )

    # A hidden release/artist should never occupy a row on a chart that's
    # already public — remove it outright instead of just sinking its rank.
    # Draft charts are left alone: editors may still be fixing the release.
    hidden_on_published = [e for e in entries if e.chart.is_published and not entry_is_public(e)]
    entries_removed = len(hidden_on_published)
    if hidden_on_published:
        RegionalChartEntry.objects.filter(id__in=[e.id for e in hidden_on_published]).delete()
        hidden_ids = {e.id for e in hidden_on_published}
        entries = [e for e in entries if e.id not in hidden_ids]

    by_scope = defaultdict(list)
    for entry in entries:
        by_scope[(entry.chart_id, entry.region)].append(entry)

    rank_changes = 0
    for scope_entries in by_scope.values():
        ordered = sorted(
            scope_entries,
            key=lambda item: (
                # See the matching comment in harmonize_chart_history: a
                # hidden release/artist sinks below public ones so it never
                # holds a public 1-50 slot.
                0 if entry_is_public(item) else 1,
                -int(item.raw_total_points or 0),
                int(item.rank) if item.rank > 0 else 0,
                item.id,
            ),
        )
        changed = []
        for rank, entry in enumerate(ordered, 1):
            expected_points = public_points(rank)
            if entry.rank != rank or entry.total_points != expected_points:
                changed.append(entry)
            entry.total_points = expected_points

        rank_changed = [entry for rank, entry in enumerate(ordered, 1) if entry.rank != rank]
        if rank_changed:
            for entry in rank_changed:
                entry.rank = -(2_000_000 + entry.id)
            RegionalChartEntry.objects.bulk_update(rank_changed, ['rank'])
            rank_changes += len(rank_changed)

        if not changed:
            continue
        for rank, entry in enumerate(ordered, 1):
            entry.rank = rank
        RegionalChartEntry.objects.bulk_update(changed, ['rank', 'total_points'])

    # Refresh in-memory ranks before rebuilding cross-month history.
    entries = list(
        RegionalChartEntry.objects.filter(chart_id__in=chart_ids, region__in=REGIONAL_CHART_CODES)
        .select_related('chart')
        .order_by('chart__chart_type', 'chart__year', 'chart__month', 'id')
    )
    public_entries = [
        entry for entry in entries
        if (
            entry.chart.is_published
            and entry.chart.status == 'published'
            and 1 <= entry.rank <= PUBLIC_CHART_LIMIT
        )
    ]
    rank_lookup = {
        (entry.chart.chart_type, entry.chart.year, entry.chart.month, entry.region, entry.release_id): entry.rank
        for entry in public_entries
    }
    historical_peaks = {}
    history_changed = []
    for entry in entries:
        history_key = (entry.chart.chart_type, entry.region, entry.release_id)
        previous_year, previous_month = _previous_period(entry.chart.year, entry.chart.month)
        previous_rank = rank_lookup.get(
            (entry.chart.chart_type, previous_year, previous_month, entry.region, entry.release_id)
        )
        if (
            entry.chart.is_published
            and entry.chart.status == 'published'
            and entry.rank <= PUBLIC_CHART_LIMIT
        ):
            peak_rank = min(historical_peaks.get(history_key, entry.rank), entry.rank)
            historical_peaks[history_key] = peak_rank
        else:
            previous_rank = None
            peak_rank = entry.rank
        if entry.prev_rank != previous_rank or entry.peak_rank != peak_rank:
            entry.prev_rank = previous_rank
            entry.peak_rank = peak_rank
            history_changed.append(entry)
    if history_changed:
        RegionalChartEntry.objects.bulk_update(history_changed, ['prev_rank', 'peak_rank'])

    return {'rank_changes': rank_changes, 'history_changes': len(history_changed), 'entries_removed': entries_removed}


@transaction.atomic
def harmonize_chart_history(chart_type=None, chart_ids=None):
    """Rebuild every derived chart field from the canonical database rows.

    A chart edit can affect much more than the row being edited: ranking,
    movement, last-month rank, historical peak, analytics, certifications,
    and year-end totals all share the same monthly history. This routine is
    deliberately backend-owned so CMS, scripts, and future clients cannot
    leave those surfaces out of sync.

    When chart_ids are supplied, expensive ranking and regional candidate
    rebuilding is limited to those changed periods. Cross-month history and
    certifications still use every period of the affected chart type.
    """
    chart_ids = [int(value) for value in (chart_ids or []) if value]
    requested_chart_ids = set(chart_ids)
    chart_types = set()
    if chart_type:
        chart_types.add(str(chart_type))
    if chart_ids:
        chart_types.update(
            MonthlyChart.objects.filter(id__in=chart_ids)
            .values_list('chart_type', flat=True)
        )
    if requested_chart_ids and not chart_types:
        return {
            'chart_types': [], 'charts': 0, 'history_charts': 0,
            'rank_changes': 0, 'scoring_changes': 0,
            'history_changes': 0, 'certifications_changed': 0,
        }
    charts_qs = MonthlyChart.objects.all()
    if chart_types:
        charts_qs = charts_qs.filter(chart_type__in=chart_types)
    history_charts = list(charts_qs.order_by('chart_type', 'year', 'month', 'id'))
    charts = (
        [chart for chart in history_charts if chart.id in requested_chart_ids]
        if requested_chart_ids else history_charts
    )
    if not charts:
        return {
            'chart_types': sorted(chart_types),
            'charts': 0,
            'history_charts': len(history_charts),
            'rank_changes': 0,
            'scoring_changes': 0,
            'history_changes': 0,
            'certifications_changed': 0,
        }

    # Restore any Combined-scope rows missing relative to the per-platform
    # aggregate (e.g. from a prior manual trim) before ranking, so they're
    # included in this pass instead of waiting for the next harmonize call.
    combined_restored = sync_combined_chart_entries(charts)

    entries = list(
        MonthlyChartEntry.objects.filter(chart_id__in=[chart.id for chart in charts])
        .select_related('chart', 'release', 'release__artist')
    )

    # A hidden release/artist (archived, merged away, etc.) should never
    # occupy a row on a chart that's already public — remove it outright
    # instead of just letting it sink in rank, so it doesn't linger as
    # CMS-only clutter or keep tripping data-quality checks. Draft charts
    # are left alone: editors may still be fixing the release before publish.
    entries_removed = 0
    hidden_on_published = [e for e in entries if e.chart.is_published and not entry_is_public(e)]
    if hidden_on_published:
        entries_removed = len(hidden_on_published)
        MonthlyChartEntry.objects.filter(id__in=[e.id for e in hidden_on_published]).delete()
        hidden_ids = {e.id for e in hidden_on_published}
        entries = [e for e in entries if e.id not in hidden_ids]

    by_scope = defaultdict(list)
    for entry in entries:
        by_scope[(entry.chart_id, entry.platform_id)].append(entry)

    rank_changes = 0
    scoring_changes = 0
    for scope_entries in by_scope.values():
        backfilled_raw_ids = set()
        for entry in scope_entries:
            if entry.raw_total_points is None:
                # Historical monthly-only rows cannot recover their original
                # raw score, so preserve the stored ordering score. Periods
                # with weekly sources are rebuilt exactly by the pipeline.
                entry.raw_total_points = max(int(entry.total_points or 0), 0)
                backfilled_raw_ids.add(entry.id)
        ordered = sorted(
            scope_entries,
            key=lambda item: (
                # A release/artist that's gone hidden (e.g. archived as a
                # merge duplicate) sinks below every public-status entry in
                # this scope, so it can never occupy a public 1-50 slot —
                # the next real candidate takes its place instead of the
                # chart quietly shrinking. entry_is_public() below.
                0 if entry_is_public(item) else 1,
                -int(item.raw_total_points or 0),
                -int(item.platform_count or 0) if item.platform_id is None else 0,
                int(item.rank or 0),
                item.id,
            ),
        )
        changed = []
        for rank, entry in enumerate(ordered, 1):
            expected_points = public_points(rank)
            expected_platform_max = (
                1 if entry.platform_id else platform_max_for(entry.chart.chart_type)
            )
            if (
                entry.rank != rank
                or entry.total_points != expected_points
                or entry.platform_max != expected_platform_max
                or entry.id in backfilled_raw_ids
            ):
                changed.append(entry)
            if entry.total_points != expected_points:
                scoring_changes += 1
            entry.total_points = expected_points
            entry.platform_max = expected_platform_max

        rank_changed = [
            entry
            for rank, entry in enumerate(ordered, 1)
            if entry.rank != rank
        ]
        if rank_changed:
            # Ranks are unique inside a chart/platform scope. Move every
            # affected row to a unique temporary value so swaps never collide.
            for entry in rank_changed:
                entry.rank = -(1_000_000 + entry.id)
            MonthlyChartEntry.objects.bulk_update(rank_changed, ['rank'])
            rank_changes += len(rank_changed)

        if not changed:
            continue
        for rank, entry in enumerate(ordered, 1):
            entry.rank = rank
        MonthlyChartEntry.objects.bulk_update(
            changed,
            ['rank', 'total_points', 'raw_total_points', 'platform_max'],
        )

    # Country-scoped charts (e.g. Kenya) are derived from the combined ranks
    # just committed above, so resync/rank them before touching history.
    regional_sync = sync_regional_chart_entries(charts)
    regional_rank = harmonize_regional_chart_entries(history_charts)

    # Refresh the in-memory ranks before rebuilding cross-month history.
    entries = list(
        MonthlyChartEntry.objects.filter(chart_id__in=[chart.id for chart in history_charts])
        .select_related('chart')
        .order_by('chart__chart_type', 'chart__year', 'chart__month', 'id')
    )
    public_entries = [
        entry for entry in entries
        if (
            entry.chart.is_published
            and entry.chart.status == 'published'
            and 1 <= entry.rank <= PUBLIC_CHART_LIMIT
        )
    ]
    rank_lookup = {
        (
            entry.chart.chart_type,
            entry.chart.year,
            entry.chart.month,
            entry.platform_id,
            entry.release_id,
        ): entry.rank
        for entry in public_entries
    }
    historical_peaks = {}
    history_changed = []
    for entry in entries:
        history_key = (
            entry.chart.chart_type,
            entry.platform_id,
            entry.release_id,
        )
        previous_year, previous_month = _previous_period(
            entry.chart.year,
            entry.chart.month,
        )
        previous_rank = rank_lookup.get((
            entry.chart.chart_type,
            previous_year,
            previous_month,
            entry.platform_id,
            entry.release_id,
        ))
        if (
            entry.chart.is_published
            and entry.chart.status == 'published'
            and entry.rank <= PUBLIC_CHART_LIMIT
        ):
            peak_rank = min(
                historical_peaks.get(history_key, entry.rank),
                entry.rank,
            )
            historical_peaks[history_key] = peak_rank
        else:
            previous_rank = None
            peak_rank = entry.rank
        if entry.prev_rank != previous_rank or entry.peak_rank != peak_rank:
            entry.prev_rank = previous_rank
            entry.peak_rank = peak_rank
            history_changed.append(entry)
    if history_changed:
        MonthlyChartEntry.objects.bulk_update(
            history_changed,
            ['prev_rank', 'peak_rank'],
        )

    affected_types = sorted({chart.chart_type for chart in history_charts})
    certifications_changed = sum(
        recalculate_certifications(chart_type=affected_type)
        for affected_type in affected_types
    )
    bump_public_revision()
    return {
        'chart_types': affected_types,
        'charts': len(charts),
        'history_charts': len(history_charts),
        'rank_changes': rank_changes,
        'scoring_changes': scoring_changes,
        'history_changes': len(history_changed),
        'certifications_changed': certifications_changed,
        'combined_restored': combined_restored['restored'],
        'regional_sync': regional_sync,
        'regional_rank_changes': regional_rank['rank_changes'],
        'entries_removed': entries_removed + regional_rank.get('entries_removed', 0),
    }
