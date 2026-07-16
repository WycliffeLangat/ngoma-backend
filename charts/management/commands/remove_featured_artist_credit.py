import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from charts.artist_credits import format_artist_list
from charts.cms_utils import bump_public_revision, sync_release_chart_entry_snapshots
from charts.models import (
    Artist,
    ChartUpload,
    MonthlyChartEntry,
    RegionalChartEntry,
    Release,
    ReleaseArtistCredit,
)


CREDIT_SPLIT_RE = re.compile(
    r'\s*(?:\||,|\bft\.?(?!\w)|\bfeat\.?(?!\w)|\bfeaturing\b|\bx\b|&)\s*',
    re.IGNORECASE,
)
CREDIT_BOUNDARY = r'(?:\||,|&|\bft\.?(?!\w)|\bfeat\.?(?!\w)|\bfeaturing\b|\bx\b)'
UPLOAD_FEATURE_KEYS = ('featured_artists', 'featured_artist', 'features', 'feat', 'fa')


def normalize(value):
    return str(value or '').strip().casefold()


def target_pattern(target):
    flexible = re.escape(str(target or '').strip()).replace(r'\ ', r'\s+')
    return re.compile(
        rf'(^|\s*{CREDIT_BOUNDARY}\s*)({flexible})(?=\s*(?:{CREDIT_BOUNDARY}|$))',
        re.IGNORECASE,
    )


def remove_credit_name(value, target):
    text = str(value or '').strip()
    if not text:
        return ''

    placeholder = '__NGOMA_REMOVE_FEATURED_ARTIST__'
    protected = target_pattern(target).sub(lambda match: f'{match.group(1)}{placeholder}', text)
    keep = []
    seen = set()
    for token in CREDIT_SPLIT_RE.split(protected):
        name = token.strip()
        key = normalize(name)
        if not key or key == normalize(placeholder) or key == normalize(target):
            continue
        if key not in seen:
            keep.append(name)
            seen.add(key)
    return format_artist_list(keep)


class Command(BaseCommand):
    help = (
        "Remove one artist name from every featured-artist credit surface: "
        "structured featured credits, release featured text, chart-entry "
        "snapshots, regional snapshots, and staged chart-upload rows. Primary "
        "artist credits are left intact."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--artist-name',
            default='Vestine & Dorcas',
            help='Featured artist name to remove. Defaults to "Vestine & Dorcas".',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually write changes. Without this flag, only reports what would change.',
        )

    def handle(self, *args, **options):
        artist_name = str(options['artist_name'] or '').strip()
        if not artist_name:
            raise SystemExit('--artist-name cannot be blank.')

        apply_changes = options['apply']
        mode = 'APPLYING' if apply_changes else 'DRY RUN (pass --apply to write)'
        self.stdout.write(self.style.WARNING(f'Mode: {mode}'))
        self.stdout.write(f'Removing featured artist credit: {artist_name!r}')

        stats = {
            'structured_featured_credits': 0,
            'release_featured_text': 0,
            'monthly_chart_entries': 0,
            'regional_chart_entries': 0,
            'chart_upload_rows': 0,
            'synced_release_snapshots': 0,
        }
        affected_release_ids = set()

        with transaction.atomic():
            featured_credits = list(
                ReleaseArtistCredit.objects.select_related('release', 'artist').filter(
                    role='featured',
                ).filter(
                    Q(artist__name__iexact=artist_name)
                    | Q(artist__display_name__iexact=artist_name)
                )
            )
            stats['structured_featured_credits'] = len(featured_credits)
            affected_release_ids.update(credit.release_id for credit in featured_credits)
            if apply_changes and featured_credits:
                ReleaseArtistCredit.objects.filter(id__in=[credit.id for credit in featured_credits]).delete()

            for release in Release.objects.filter(featured_artists__icontains=artist_name.split()[0]).iterator():
                cleaned = remove_credit_name(release.featured_artists, artist_name)
                if cleaned == (release.featured_artists or ''):
                    continue
                stats['release_featured_text'] += 1
                affected_release_ids.add(release.id)
                if apply_changes:
                    release.featured_artists = cleaned
                    release.save(update_fields=['featured_artists', 'updated_at'])

            for entry in MonthlyChartEntry.objects.filter(featured_artists__icontains=artist_name.split()[0]).iterator():
                cleaned = remove_credit_name(entry.featured_artists, artist_name)
                if cleaned == (entry.featured_artists or ''):
                    continue
                stats['monthly_chart_entries'] += 1
                affected_release_ids.add(entry.release_id)
                if apply_changes:
                    entry.featured_artists = cleaned
                    entry.save(update_fields=['featured_artists'])

            for entry in RegionalChartEntry.objects.filter(featured_artists__icontains=artist_name.split()[0]).iterator():
                cleaned = remove_credit_name(entry.featured_artists, artist_name)
                if cleaned == (entry.featured_artists or ''):
                    continue
                stats['regional_chart_entries'] += 1
                affected_release_ids.add(entry.release_id)
                if apply_changes:
                    entry.featured_artists = cleaned
                    entry.save(update_fields=['featured_artists'])

            for upload in ChartUpload.objects.exclude(rows_data=[]).only('id', 'rows_data').iterator():
                rows = upload.rows_data if isinstance(upload.rows_data, list) else []
                changed = False
                changed_rows = 0
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    row_changed = False
                    for key in UPLOAD_FEATURE_KEYS:
                        if key not in row:
                            continue
                        cleaned = remove_credit_name(row.get(key), artist_name)
                        if cleaned != str(row.get(key) or '').strip():
                            row[key] = cleaned
                            changed = True
                            row_changed = True
                    if row_changed:
                        changed_rows += 1
                if changed:
                    stats['chart_upload_rows'] += changed_rows
                    if apply_changes:
                        ChartUpload.objects.filter(pk=upload.pk).update(rows_data=rows)

            if apply_changes and affected_release_ids:
                for release in Release.objects.filter(id__in=affected_release_ids).prefetch_related('artist_credits__artist'):
                    result = sync_release_chart_entry_snapshots(release)
                    stats['synced_release_snapshots'] += result['updated']

            if apply_changes and any(stats.values()):
                bump_public_revision()

        for key, value in stats.items():
            self.stdout.write(f'{key}: {value}')
        self.stdout.write(f'affected_releases: {len(affected_release_ids)}')
