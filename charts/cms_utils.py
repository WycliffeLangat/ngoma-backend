import csv
import io
import re
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from django.utils import timezone
from django.utils.text import slugify
import openpyxl
from .models import AuditLog, Artist, Release, ReleaseArtistCredit, MonthlyChart, MonthlyChartEntry, Platform, ChartType, CertificationRule, Certification, SiteSetting


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
    ReleaseArtistCredit.objects.get_or_create(
        release=release,
        artist=artist,
        role='primary',
        defaults={'position': 0},
    )
    return release


def detect_entry_status(row, chart_type, platform, year, month):
    if not (year and month and row.get('title') and row.get('artist')):
        return 'unknown'
    artist = find_artist_by_name(row.get('artist'))
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
    if chart.locked:
        raise ValueError('This chart month is locked. Unlock it before replacing data.')
    MonthlyChartEntry.objects.filter(chart=chart, platform=platform).delete()
    entries = []
    for row in sorted(upload.rows_data or [], key=lambda r: int(r.get('rank') or 9999)):
        artist = get_or_create_cms_artist(row.get('artist'), row.get('country'), row.get('country_code'))
        release = get_or_create_cms_release(row, artist, upload.chart_type)
        max_size = platform.max_chart_size if platform else 50
        points = row.get('total_points')
        if points is None:
            points = max(max_size - int(row.get('rank') or 0) + 1, 0)
        entries.append(MonthlyChartEntry(
            chart=chart,
            platform=platform,
            release=release,
            rank=int(row.get('rank') or len(entries) + 1),
            total_points=int(points or 0),
            weeks_on_chart=int(row.get('weeks_on_chart') or 1),
            platform_count=int(row.get('platform_count') or (1 if platform else 0)),
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
    recalculate_certifications(chart_type=upload.chart_type)
    return chart, len(entries)


def certification_thresholds():
    rules = CertificationRule.objects.filter(active=True)
    if rules.exists():
        return {r.level: r.threshold for r in rules}
    return Certification.THRESHOLDS


def recalculate_certifications(chart_type=None, release=None):
    from django.db.models import Sum
    qs = Release.objects.all()
    if chart_type:
        qs = qs.filter(chart_type=chart_type)
    if release:
        qs = qs.filter(pk=release.pk)
    thresholds = certification_thresholds()
    updated = 0
    for rel in qs:
        total = MonthlyChartEntry.objects.filter(release=rel, platform__isnull=True).aggregate(total=Sum('total_points'))['total'] or 0
        for level, threshold in sorted(thresholds.items(), key=lambda item: item[1]):
            if total >= threshold:
                Certification.objects.update_or_create(release=rel, level=level, defaults={'total_points': total})
                updated += 1
    return updated
