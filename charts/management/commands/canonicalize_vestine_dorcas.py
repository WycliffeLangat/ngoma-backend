import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from charts.artist_credits import (
    NON_COLLABORATION_ARTIST_NAMES,
    format_artist_list,
    should_preserve_registered_artist_name,
)
from charts.cms_utils import bump_public_revision, harmonize_chart_history, sync_release_chart_entry_snapshots, unique_slug
from charts.models import Artist, ChartUpload, MonthlyChartEntry, RegionalChartEntry, Release, ReleaseArtistCredit


CANONICAL_NAME = 'Vestine & Dorcas'
TARGET_ALIASES = ('Vestine & Dorcas', 'Vestine', 'Dorcas')
ALLOWED_CANONICAL_TITLES = ('yebo (nitawale)', 'emmanuel')
PRIMARY_UPLOAD_KEYS = ('artist', 'primary_artist', 'primary_artist_credit', 'a', 'pa')
FEATURED_UPLOAD_KEYS = ('featured_artists', 'featured_artist', 'features', 'feat', 'fa')
CREDITED_UPLOAD_KEYS = ('credited_artists', 'credits')
CREDIT_SPLIT_RE = re.compile(
    r'\s*(?:\||,|\bft\.?(?!\w)|\bfeat\.?(?!\w)|\bfeaturing\b|\bx\b|&)\s*',
    re.IGNORECASE,
)
CREDIT_BOUNDARY = r'(?:\||,|&|\bft\.?(?!\w)|\bfeat\.?(?!\w)|\bfeaturing\b|\bx\b)'


def norm(value):
    return str(value or '').strip().casefold()


def title_key(release):
    return norm(release.canonical_title or release.title)


def row_title_key(row):
    return norm(row.get('canonical_title') or row.get('title') or row.get('t'))


def target_keys():
    return {norm(name) for name in TARGET_ALIASES}


def target_pattern(target):
    flexible = re.escape(str(target or '').strip()).replace(r'\ ', r'\s+')
    return re.compile(
        rf'(^|\s*{CREDIT_BOUNDARY}\s*)({flexible})(?=\s*(?:{CREDIT_BOUNDARY}|$))',
        re.IGNORECASE,
    )


def protect_credit_names(value, protected_names):
    text = str(value or '').strip()
    replacements = {}
    protected = text
    for index, name in enumerate(sorted(protected_names or (), key=len, reverse=True)):
        if not str(name or '').strip():
            continue
        placeholder = f'__NGOMA_PROTECTED_ARTIST_{index}__'

        def replace(match):
            replacements[norm(placeholder)] = match.group(2).strip()
            return f'{match.group(1)}{placeholder}'

        protected = target_pattern(name).sub(replace, protected)
    return protected, replacements


def credit_mentions_target(value, protected_names=()):
    text = str(value or '').strip()
    if not text:
        return False
    protected, replacements = protect_credit_names(text, protected_names)
    keys = target_keys()
    if norm(protected) in keys:
        return True
    return any(
        norm(part) in keys
        for part in CREDIT_SPLIT_RE.split(protected)
        if str(part or '').strip() and norm(part) not in replacements
    )


def remove_target_credits(value, protected_names=()):
    text = str(value or '').strip()
    if not text:
        return ''
    placeholder = '__NGOMA_REMOVE_TARGET_ARTIST__'
    protected, protected_replacements = protect_credit_names(text, protected_names)
    for name in sorted(TARGET_ALIASES, key=len, reverse=True):
        protected = target_pattern(name).sub(lambda match: f'{match.group(1)}{placeholder}', protected)
    keep = []
    seen = set()
    for token in CREDIT_SPLIT_RE.split(protected):
        name = token.strip()
        key = norm(name)
        if not key or key == norm(placeholder) or key in target_keys():
            continue
        if key in protected_replacements:
            name = protected_replacements[key]
            key = norm(name)
        if key not in seen:
            keep.append(name)
            seen.add(key)
    return format_artist_list(keep)


def split_credit_names(value, protected_names=()):
    text = str(value or '').strip()
    if not text:
        return []
    protected, protected_replacements = protect_credit_names(text, protected_names)
    names = []
    for token in CREDIT_SPLIT_RE.split(protected):
        name = token.strip()
        key = norm(name)
        if not key:
            continue
        names.append(protected_replacements.get(key, name))
    return names


def artist_display_name(artist):
    return str(getattr(artist, 'display_name', '') or getattr(artist, 'name', '') or '').strip()


def artist_is_target(artist):
    if not artist:
        return False
    names = [artist.name, artist.display_name, *(artist.aliases or [])]
    return any(norm(name) in target_keys() for name in names)


def protected_credit_names(target_artist_ids):
    names = set(NON_COLLABORATION_ARTIST_NAMES)
    for artist in Artist.objects.all().iterator():
        if artist.id in target_artist_ids or artist_is_target(artist):
            continue
        for name in [artist.name, artist.display_name, *(artist.aliases or [])]:
            if should_preserve_registered_artist_name(name, artist):
                names.add(str(name or '').strip())
    return names


def credit_sort_key(credit):
    return (credit.position, credit.pk or 0)


def merged_featured_text(cleaned_text, featured_artists, protected_names):
    return format_artist_list([
        *split_credit_names(cleaned_text, protected_names),
        *(artist_display_name(artist) for artist in featured_artists),
    ])


class Command(BaseCommand):
    help = (
        "Canonicalize Vestine & Dorcas as one group artist. The group may only "
        "appear on Yebo (Nitawale) and Emmanuel; target aliases are removed from "
        "featured credits and from disallowed structured credits where a safe "
        "non-target primary artist already exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually write changes. Without this flag, only reports what would change.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        mode = 'APPLYING' if apply_changes else 'DRY RUN (pass --apply to write)'
        self.stdout.write(self.style.WARNING(f'Mode: {mode}'))

        stats = {
            'canonical_artist_created': 0,
            'canonical_artist_metadata_cleaned': 0,
            'allowed_releases_canonicalized': 0,
            'disallowed_featured_removed': 0,
            'disallowed_primary_removed': 0,
            'disallowed_releases_archived': 0,
            'credited_metadata_cleaned': 0,
            'snapshot_featured_cleaned': 0,
            'upload_rows_updated': 0,
            'standalone_artists_archived': 0,
            'snapshot_rows_synced': 0,
        }
        archived_releases = []
        affected_release_ids = set()

        with transaction.atomic():
            group = (
                Artist.objects.filter(name__iexact=CANONICAL_NAME).first()
                or Artist.objects.filter(display_name__iexact=CANONICAL_NAME).first()
            )
            source_artist = Artist.objects.filter(name__iexact='Vestine').first() or Artist.objects.filter(name__iexact='Dorcas').first()
            if not group:
                stats['canonical_artist_created'] = 1
                if apply_changes:
                    group = Artist.objects.create(
                        name=CANONICAL_NAME,
                        display_name=CANONICAL_NAME,
                        slug=unique_slug(Artist, CANONICAL_NAME),
                        artist_type='group',
                        country=getattr(source_artist, 'country', '') or '',
                        country_code=getattr(source_artist, 'country_code', '') or '',
                        status='active',
                    )
                else:
                    group = Artist(name=CANONICAL_NAME, artist_type='group')
            elif group:
                updates = []
                if group.name != CANONICAL_NAME:
                    updates.append('name')
                if group.display_name != CANONICAL_NAME:
                    updates.append('display_name')
                if group.artist_type != 'group':
                    updates.append('artist_type')
                if group.status == 'archived':
                    updates.append('status')
                cleaned_aliases = [
                    alias for alias in (group.aliases or [])
                    if norm(alias) not in {norm('Vestine'), norm('Dorcas'), norm(CANONICAL_NAME)}
                ]
                if cleaned_aliases != (group.aliases or []):
                    updates.append('aliases')
                if updates:
                    stats['canonical_artist_metadata_cleaned'] = 1
                    if apply_changes:
                        group.name = CANONICAL_NAME
                        group.display_name = CANONICAL_NAME
                        group.artist_type = 'group'
                        if group.status == 'archived':
                            group.status = 'active'
                        group.aliases = cleaned_aliases
                        group.save(update_fields=[*updates, 'updated_at'])

            target_artist_ids = set(
                Artist.objects.filter(
                    Q(name__iexact='Vestine')
                    | Q(name__iexact='Dorcas')
                    | Q(name__iexact=CANONICAL_NAME)
                    | Q(display_name__iexact=CANONICAL_NAME)
                ).values_list('id', flat=True)
            )
            if getattr(group, 'id', None):
                target_artist_ids.add(group.id)
            protected_names = protected_credit_names(target_artist_ids)

            def clean_entry_snapshots(model):
                cleaned_count = 0
                entries = model.objects.filter(
                    Q(featured_artists__icontains='Vestine')
                    | Q(featured_artists__icontains='Dorcas')
                )
                for entry in entries.iterator():
                    cleaned_featured = remove_target_credits(entry.featured_artists, protected_names)
                    if cleaned_featured == str(entry.featured_artists or '').strip():
                        continue
                    cleaned_count += 1
                    if apply_changes:
                        model.objects.filter(pk=entry.pk).update(featured_artists=cleaned_featured)
                return cleaned_count

            releases = (
                Release.objects.select_related('artist')
                .prefetch_related('artist_credits__artist')
                .filter(
                    Q(artist_id__in=target_artist_ids)
                    | Q(artist_credits__artist_id__in=target_artist_ids)
                    | Q(featured_artists__icontains='Vestine')
                    | Q(featured_artists__icontains='Dorcas')
                    | Q(credited_artists__icontains='Vestine')
                    | Q(credited_artists__icontains='Dorcas')
                    | Q(canonical_title__in=ALLOWED_CANONICAL_TITLES)
                )
                .distinct()
            )

            for release in releases:
                is_allowed = title_key(release) in ALLOWED_CANONICAL_TITLES
                credits = list(release.artist_credits.select_related('artist').all())
                primary = sorted([credit for credit in credits if credit.role == 'primary'], key=credit_sort_key)
                featured = sorted([credit for credit in credits if credit.role == 'featured'], key=credit_sort_key)
                release_changed = False

                if is_allowed:
                    stats['allowed_releases_canonicalized'] += 1
                    affected_release_ids.add(release.id)
                    non_target_primary = [credit.artist for credit in primary if not artist_is_target(credit.artist)]
                    desired_primary = [group, *non_target_primary]
                    desired_featured = [credit.artist for credit in featured if not artist_is_target(credit.artist)]
                    cleaned_featured_text = merged_featured_text(
                        remove_target_credits(release.featured_artists, protected_names),
                        desired_featured,
                        protected_names,
                    )
                    cleaned_credited_text = remove_target_credits(release.credited_artists, protected_names)
                    if apply_changes:
                        ReleaseArtistCredit.objects.filter(release=release, role='primary').delete()
                        ReleaseArtistCredit.objects.filter(
                            release=release,
                            role='featured',
                            artist_id__in=target_artist_ids,
                        ).delete()
                        for position, artist in enumerate(desired_primary):
                            ReleaseArtistCredit.objects.update_or_create(
                                release=release,
                                artist=artist,
                                role='primary',
                                defaults={'position': position},
                            )
                        existing_featured_ids = set()
                        for position, artist in enumerate(desired_featured):
                            if artist.id in existing_featured_ids or artist.id in {item.id for item in desired_primary}:
                                continue
                            existing_featured_ids.add(artist.id)
                            ReleaseArtistCredit.objects.update_or_create(
                                release=release,
                                artist=artist,
                                role='featured',
                                defaults={'position': position},
                            )
                        release.artist = group
                        release.featured_artists = cleaned_featured_text
                        release.credited_artists = cleaned_credited_text
                        release.save(update_fields=['artist', 'featured_artists', 'credited_artists', 'updated_at'])
                    continue

                target_featured = [credit for credit in featured if artist_is_target(credit.artist)]
                desired_featured = [credit.artist for credit in featured if not artist_is_target(credit.artist)]
                cleaned_featured_text = merged_featured_text(
                    remove_target_credits(release.featured_artists, protected_names),
                    desired_featured,
                    protected_names,
                )
                cleaned_credited_text = remove_target_credits(release.credited_artists, protected_names)
                if target_featured or cleaned_featured_text != (release.featured_artists or ''):
                    stats['disallowed_featured_removed'] += 1
                    affected_release_ids.add(release.id)
                    release_changed = True
                    if apply_changes:
                        ReleaseArtistCredit.objects.filter(
                            id__in=[credit.id for credit in target_featured]
                        ).delete()
                        release.featured_artists = cleaned_featured_text

                if cleaned_credited_text != (release.credited_artists or ''):
                    stats['credited_metadata_cleaned'] += 1
                    affected_release_ids.add(release.id)
                    release_changed = True
                    if apply_changes:
                        release.credited_artists = cleaned_credited_text

                target_primary = [credit for credit in primary if artist_is_target(credit.artist)]
                non_target_primary = [credit.artist for credit in primary if not artist_is_target(credit.artist)]
                if artist_is_target(release.artist) or target_primary:
                    if non_target_primary:
                        stats['disallowed_primary_removed'] += 1
                        affected_release_ids.add(release.id)
                        release_changed = True
                        if apply_changes:
                            ReleaseArtistCredit.objects.filter(release=release, role='primary').delete()
                            release.artist = non_target_primary[0]
                            for position, artist in enumerate(non_target_primary):
                                ReleaseArtistCredit.objects.update_or_create(
                                    release=release,
                                    artist=artist,
                                    role='primary',
                                    defaults={'position': position},
                                )
                    else:
                        stats['disallowed_releases_archived'] += 1
                        affected_release_ids.add(release.id)
                        release_changed = True
                        archived_releases.append(f'{release.id}: {release.title} ({release.artist.name})')
                        if apply_changes:
                            ReleaseArtistCredit.objects.filter(release=release).delete()
                            release.featured_artists = ''
                            release.credited_artists = ''
                            release.status = 'archived'

                if apply_changes and release_changed:
                    release.save(update_fields=['artist', 'featured_artists', 'credited_artists', 'status', 'updated_at'])

            stats['snapshot_featured_cleaned'] += clean_entry_snapshots(MonthlyChartEntry)
            stats['snapshot_featured_cleaned'] += clean_entry_snapshots(RegionalChartEntry)

            for upload in ChartUpload.objects.exclude(rows_data=[]).only('id', 'rows_data').iterator():
                rows = upload.rows_data if isinstance(upload.rows_data, list) else []
                changed = False
                changed_rows = 0
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    allowed_row = row_title_key(row) in ALLOWED_CANONICAL_TITLES
                    row_changed = False
                    for key in FEATURED_UPLOAD_KEYS:
                        if key not in row:
                            continue
                        cleaned = remove_target_credits(row.get(key), protected_names)
                        if cleaned != str(row.get(key) or '').strip():
                            row[key] = cleaned
                            row_changed = True
                    for key in CREDITED_UPLOAD_KEYS:
                        if key not in row:
                            continue
                        cleaned = remove_target_credits(row.get(key), protected_names)
                        if cleaned != str(row.get(key) or '').strip():
                            row[key] = cleaned
                            row_changed = True
                    if allowed_row:
                        for key in PRIMARY_UPLOAD_KEYS:
                            if key in row and credit_mentions_target(row.get(key), protected_names):
                                row[key] = CANONICAL_NAME
                                row_changed = True
                    else:
                        for key in PRIMARY_UPLOAD_KEYS:
                            if key not in row or not credit_mentions_target(row.get(key), protected_names):
                                continue
                            row[key] = remove_target_credits(row.get(key), protected_names)
                            row_changed = True
                    if row_changed:
                        changed = True
                        changed_rows += 1
                if changed:
                    stats['upload_rows_updated'] += changed_rows
                    if apply_changes:
                        ChartUpload.objects.filter(pk=upload.pk).update(rows_data=rows)

            if apply_changes and affected_release_ids:
                chart_ids = list(
                    MonthlyChartEntry.objects.filter(release_id__in=affected_release_ids)
                    .values_list('chart_id', flat=True).distinct()
                )
                for release in Release.objects.filter(id__in=affected_release_ids).prefetch_related('artist_credits__artist'):
                    result = sync_release_chart_entry_snapshots(release)
                    stats['snapshot_rows_synced'] += result['updated']
                if chart_ids:
                    harmonize_chart_history(chart_ids=chart_ids)

            if apply_changes:
                for artist in Artist.objects.filter(name__in=['Vestine', 'Dorcas']):
                    still_referenced = (
                        Release.objects.filter(artist=artist).exclude(status='archived').exists()
                        or ReleaseArtistCredit.objects.filter(artist=artist)
                        .exclude(release__status='archived')
                        .exists()
                    )
                    if not still_referenced and artist.status != 'archived':
                        artist.status = 'archived'
                        artist.save(update_fields=['status', 'updated_at'])
                        stats['standalone_artists_archived'] += 1

            if apply_changes and any(value for key, value in stats.items() if key != 'unresolved_releases'):
                bump_public_revision()

            if not apply_changes:
                transaction.set_rollback(True)

        for key, value in stats.items():
            self.stdout.write(f'{key}: {value}')
        if archived_releases:
            self.stdout.write(self.style.WARNING('Archived disallowed target-only releases with no safe replacement artist:'))
            for item in archived_releases[:50]:
                self.stdout.write(f'  {item}')
