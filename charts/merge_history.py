from datetime import date, datetime, time

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from .models import (
    Artist,
    Certification,
    MergeHistory,
    MonthlyChart,
    MonthlyChartEntry,
    NormalizationRule,
    PlatformChartEntry,
    Release,
    ReleaseArtistCredit,
    WeeklyUpload,
)


RELEASE_MERGE_META_FIELDS = [
    'cover_image', 'genre', 'label', 'distributor', 'isrc', 'upc',
    'release_year', 'release_date', 'songwriters', 'producers',
    'spotify_url', 'apple_music_url', 'youtube_url', 'boomplay_url',
    'audiomack_url', 'tiktok_url', 'shazam_url', 'radio_info',
]


class MergeUndoError(ValueError):
    pass


def _field_key(field):
    return field.attname if getattr(field, 'many_to_one', False) else field.name


def _json_field_value(field, value):
    if field.get_internal_type() in {'FileField', 'ImageField'}:
        return getattr(value, 'name', '') or ''
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def model_snapshot(instance):
    if instance is None:
        return None
    data = {}
    for field in instance._meta.fields:
        key = _field_key(field)
        data[key] = _json_field_value(field, getattr(instance, key))
    return data


def _coerce_for_field(field, value):
    if value in ('', None):
        return value
    internal_type = field.get_internal_type()
    if internal_type == 'DateField':
        return parse_date(value) if isinstance(value, str) else value
    if internal_type == 'DateTimeField':
        return parse_datetime(value) if isinstance(value, str) else value
    if internal_type == 'TimeField':
        return parse_time(value) if isinstance(value, str) else value
    return value


def _create_model_from_snapshot(model, snapshot, overrides=None, preserve_pk=True):
    overrides = overrides or {}
    payload = {}
    for field in model._meta.fields:
        key = _field_key(field)
        if field.primary_key and not preserve_pk:
            continue
        if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
            continue
        if key in snapshot:
            payload[key] = _coerce_for_field(field, snapshot[key])
    payload.update(overrides)
    return model.objects.create(**payload)


def _set_model_fields_from_snapshot(instance, snapshot, field_names):
    changed = []
    field_by_name = {field.name: field for field in instance._meta.fields}
    field_by_name.update({_field_key(field): field for field in instance._meta.fields})
    for name in field_names:
        field = field_by_name.get(name)
        if not field:
            continue
        key = _field_key(field)
        if key not in snapshot:
            continue
        value = _coerce_for_field(field, snapshot[key])
        if getattr(instance, key) != value:
            setattr(instance, key, value)
            changed.append(field.name)
    if changed:
        instance.save(update_fields=sorted(set(changed)))
    return changed


def _normalization_snapshots(rule_type, raw_values):
    raw_values = [str(value or '').strip() for value in raw_values if str(value or '').strip()]
    if not raw_values:
        return []
    query = Q()
    for raw_value in raw_values:
        query |= Q(raw_value__iexact=raw_value)
    return [
        model_snapshot(rule)
        for rule in NormalizationRule.objects.filter(rule_type=rule_type).filter(query).order_by('id')
    ]


def _restore_normalization_rules(rule_type, raw_values, canonical_value, before_snapshots):
    restored = 0
    removed = 0
    by_raw = {
        str(snapshot.get('raw_value') or '').casefold(): snapshot
        for snapshot in before_snapshots or []
    }
    for raw_value in [str(value or '').strip() for value in raw_values if str(value or '').strip()]:
        existing = NormalizationRule.objects.filter(rule_type=rule_type, raw_value__iexact=raw_value)
        previous = by_raw.get(raw_value.casefold())
        if previous:
            rule = existing.first()
            if rule:
                changed = _set_model_fields_from_snapshot(
                    rule,
                    previous,
                    ['raw_value', 'canonical_value', 'notes'],
                )
                restored += 1 if changed else 0
            else:
                _create_model_from_snapshot(NormalizationRule, previous, preserve_pk=False)
                restored += 1
        else:
            deleted, _ = existing.filter(canonical_value__iexact=canonical_value).delete()
            removed += deleted
    return {'restored': restored, 'removed': removed}


def _release_label(release):
    artist = release.artist.display_name or release.artist.name
    return f'{release.title} by {artist}'


def _artist_label(artist):
    return artist.display_name or artist.name


def _release_rule_row(release):
    artist = release.artist.display_name or release.artist.name
    return {
        'id': release.id,
        '_type': 'release',
        '_chartType': release.chart_type,
        'title': release.title,
        'canonical_title': release.canonical_title,
        'artist_display': artist,
        'artist_name': artist,
    }


def _artist_rule_row(artist):
    return {
        'id': artist.id,
        '_type': 'artist',
        'name': artist.name,
        'display_name': artist.display_name,
        'aliases': artist.aliases or [],
    }


def _release_state_snapshot(duplicate, keeper=None):
    monthly_entries = []
    for entry in MonthlyChartEntry.objects.filter(release=duplicate).order_by('id'):
        keeper_entry = None
        if keeper is not None:
            keeper_entry = MonthlyChartEntry.objects.filter(
                chart_id=entry.chart_id,
                platform_id=entry.platform_id,
                release=keeper,
            ).first()
        monthly_entries.append({
            'action': 'summed' if keeper_entry else 'moved',
            'duplicate_entry': model_snapshot(entry),
            'keeper_entry_before': model_snapshot(keeper_entry),
        })

    keeper_pce_pairs = set()
    if keeper is not None:
        keeper_pce_pairs = set(
            PlatformChartEntry.objects.filter(release=keeper).values_list('upload_id', 'platform_id')
        )
    platform_entries = []
    for entry in PlatformChartEntry.objects.filter(release=duplicate).order_by('id'):
        platform_entries.append({
            'action': 'dropped' if (entry.upload_id, entry.platform_id) in keeper_pce_pairs else 'moved',
            'entry': model_snapshot(entry),
        })

    return {
        'release': model_snapshot(duplicate),
        'release_artist_credits': [
            model_snapshot(credit)
            for credit in ReleaseArtistCredit.objects.filter(release=duplicate).order_by('id')
        ],
        'certifications': [
            model_snapshot(cert)
            for cert in Certification.objects.filter(release=duplicate).order_by('id')
        ],
        'monthly_entries': monthly_entries,
        'platform_entries': platform_entries,
    }


def create_release_merge_history(duplicate, keeper, user=None):
    keeper_before = model_snapshot(keeper)
    duplicate_before = model_snapshot(duplicate)
    restorable_fields = {}
    for field in RELEASE_MERGE_META_FIELDS:
        duplicate_value = getattr(duplicate, field)
        keeper_value = getattr(keeper, field)
        if duplicate_value and not keeper_value:
            model_field = duplicate._meta.get_field(field)
            restorable_fields[field] = {
                'before': keeper_before.get(field),
                'copied': _json_field_value(model_field, duplicate_value),
            }

    affected_chart_ids = sorted(set(
        MonthlyChartEntry.objects.filter(Q(release=duplicate) | Q(release=keeper))
        .values_list('chart_id', flat=True)
    ))

    snapshot = {
        'version': 1,
        'merge_type': MergeHistory.MergeType.RELEASE,
        'keeper': keeper_before,
        'duplicate': duplicate_before,
        'keeper_rule_row': _release_rule_row(keeper),
        'duplicate_rule_row': _release_rule_row(duplicate),
        'keeper_restorable_fields': restorable_fields,
        'release_state': _release_state_snapshot(duplicate, keeper),
        'normalization': {
            'rule_type': 'title',
            'raw_values': [duplicate.title],
            'canonical_value': keeper.title,
            'before': _normalization_snapshots('title', [duplicate.title]),
        },
        'affected_chart_ids': affected_chart_ids,
        'chart_type': keeper.chart_type,
    }
    return MergeHistory.objects.create(
        merge_type=MergeHistory.MergeType.RELEASE,
        keeper_id=keeper.id,
        keeper_label=_release_label(keeper),
        duplicate_id=duplicate.id,
        duplicate_label=_release_label(duplicate),
        snapshot=snapshot,
        merged_by=user if user and user.is_authenticated else None,
    )


def create_artist_merge_history(primary, duplicate, user=None):
    primary_canonical = {
        (release.canonical_title, release.chart_type): release
        for release in Release.objects.filter(artist=primary).select_related('artist').order_by('id')
    }
    direct_releases = []
    for release in Release.objects.filter(artist=duplicate).select_related('artist').order_by('id'):
        keeper_release = primary_canonical.get((release.canonical_title, release.chart_type))
        direct_releases.append({
            'action': 'merged_release' if keeper_release else 'moved_release',
            'keeper_release_id': keeper_release.id if keeper_release else None,
            'keeper_release_rule_row': _release_rule_row(keeper_release) if keeper_release else None,
            'state': _release_state_snapshot(release, keeper_release),
        })

    affected_chart_ids = sorted(set(
        MonthlyChartEntry.objects.filter(
            Q(release__artist=duplicate) | Q(release__artist_credits__artist=duplicate)
            | Q(release__artist=primary) | Q(release__artist_credits__artist=primary)
        ).values_list('chart_id', flat=True)
    ))
    raw_values = [duplicate.name, *(duplicate.aliases or [])]
    snapshot = {
        'version': 1,
        'merge_type': MergeHistory.MergeType.ARTIST,
        'primary': model_snapshot(primary),
        'duplicate': model_snapshot(duplicate),
        'keeper_rule_row': _artist_rule_row(primary),
        'duplicate_rule_row': _artist_rule_row(duplicate),
        'direct_releases': direct_releases,
        'artist_credits': [
            model_snapshot(credit)
            for credit in ReleaseArtistCredit.objects.filter(artist=duplicate).order_by('id')
        ],
        'normalization': {
            'rule_type': 'artist',
            'raw_values': raw_values,
            'canonical_value': primary.name,
            'before': _normalization_snapshots('artist', raw_values),
        },
        'affected_chart_ids': affected_chart_ids,
    }
    return MergeHistory.objects.create(
        merge_type=MergeHistory.MergeType.ARTIST,
        keeper_id=primary.id,
        keeper_label=_artist_label(primary),
        duplicate_id=duplicate.id,
        duplicate_label=_artist_label(duplicate),
        snapshot=snapshot,
        merged_by=user if user and user.is_authenticated else None,
    )


def _platform_filter(qs, platform_id):
    if platform_id is None:
        return qs.filter(platform__isnull=True)
    return qs.filter(platform_id=platform_id)


def _safe_monthly_rank(chart_id, platform_id, preferred_rank, preferred_id):
    qs = MonthlyChartEntry.objects.filter(chart_id=chart_id, rank=preferred_rank)
    qs = _platform_filter(qs, platform_id)
    if not qs.exists():
        return preferred_rank
    seed = int(preferred_id or 0)
    rank = -(5_000_000 + seed)
    while _platform_filter(
        MonthlyChartEntry.objects.filter(chart_id=chart_id, rank=rank),
        platform_id,
    ).exists():
        rank -= 1
    return rank


def _create_monthly_entry(snapshot, release_id):
    if not snapshot:
        return None
    if not Release.objects.filter(pk=release_id).exists():
        return None
    if not MonthlyChart.objects.filter(pk=snapshot.get('chart_id')).exists():
        return None
    rank = _safe_monthly_rank(
        snapshot.get('chart_id'),
        snapshot.get('platform_id'),
        snapshot.get('rank'),
        snapshot.get('id'),
    )
    preserve_pk = not MonthlyChartEntry.objects.filter(pk=snapshot.get('id')).exists()
    return _create_model_from_snapshot(
        MonthlyChartEntry,
        snapshot,
        overrides={'release_id': release_id, 'rank': rank},
        preserve_pk=preserve_pk,
    )


def _restore_monthly_entries(entry_actions, duplicate, keeper):
    stats = {'moved_back': 0, 'recreated': 0, 'keeper_entries_restored': 0, 'skipped': 0}
    for action in entry_actions or []:
        duplicate_entry = action.get('duplicate_entry') or {}
        entry = MonthlyChartEntry.objects.filter(pk=duplicate_entry.get('id')).first()
        if action.get('action') == 'moved':
            if entry:
                if entry.release_id == keeper.id:
                    entry.release = duplicate
                    entry.save(update_fields=['release'])
                    stats['moved_back'] += 1
                elif entry.release_id == duplicate.id:
                    stats['moved_back'] += 1
                else:
                    stats['skipped'] += 1
            elif _create_monthly_entry(duplicate_entry, duplicate.id):
                stats['recreated'] += 1
            else:
                stats['skipped'] += 1
            continue

        keeper_before = action.get('keeper_entry_before') or {}
        keeper_entry = None
        if keeper_before.get('id'):
            keeper_entry = MonthlyChartEntry.objects.filter(pk=keeper_before['id'], release=keeper).first()
        if not keeper_entry and keeper_before:
            qs = MonthlyChartEntry.objects.filter(
                chart_id=keeper_before.get('chart_id'),
                release=keeper,
            )
            qs = _platform_filter(qs, keeper_before.get('platform_id'))
            keeper_entry = qs.first()
        if keeper_entry:
            changed = _set_model_fields_from_snapshot(
                keeper_entry,
                keeper_before,
                ['raw_total_points', 'weeks_on_chart', 'platform_count', 'platform_max', 'peak_rank', 'featured_artists', 'release_year', 'confidence'],
            )
            if changed:
                stats['keeper_entries_restored'] += 1

        if entry:
            if entry.release_id == keeper.id:
                entry.release = duplicate
                entry.save(update_fields=['release'])
                stats['moved_back'] += 1
            elif entry.release_id == duplicate.id:
                stats['recreated'] += 1
            else:
                stats['skipped'] += 1
        elif _create_monthly_entry(duplicate_entry, duplicate.id):
            stats['recreated'] += 1
        else:
            stats['skipped'] += 1
    return stats


def _create_platform_entry(snapshot, release_id):
    if not snapshot:
        return None
    if not WeeklyUpload.objects.filter(pk=snapshot.get('upload_id')).exists():
        return None
    position_taken = PlatformChartEntry.objects.filter(
        upload_id=snapshot.get('upload_id'),
        platform_id=snapshot.get('platform_id'),
        position=snapshot.get('position'),
    ).exists()
    if position_taken:
        return None
    preserve_pk = not PlatformChartEntry.objects.filter(pk=snapshot.get('id')).exists()
    return _create_model_from_snapshot(
        PlatformChartEntry,
        snapshot,
        overrides={'release_id': release_id},
        preserve_pk=preserve_pk,
    )


def _restore_platform_entries(entry_actions, duplicate, keeper):
    stats = {'moved_back': 0, 'recreated': 0, 'skipped': 0}
    for action in entry_actions or []:
        snapshot = action.get('entry') or {}
        entry = PlatformChartEntry.objects.filter(pk=snapshot.get('id')).first()
        if action.get('action') == 'moved' and entry:
            if entry.release_id == keeper.id:
                entry.release = duplicate
                entry.save(update_fields=['release'])
                stats['moved_back'] += 1
            elif entry.release_id == duplicate.id:
                stats['moved_back'] += 1
            else:
                stats['skipped'] += 1
            continue
        if _create_platform_entry(snapshot, duplicate.id):
            stats['recreated'] += 1
        else:
            stats['skipped'] += 1
    return stats


def _next_credit_position(release_id, role):
    max_position = (
        ReleaseArtistCredit.objects.filter(release_id=release_id, role=role)
        .aggregate(value=Max('position'))['value']
    )
    return 0 if max_position is None else max_position + 1


def _restore_artist_credit(snapshot, release_id=None, artist_id=None):
    release_id = release_id or snapshot.get('release_id')
    artist_id = artist_id or snapshot.get('artist_id')
    role = snapshot.get('role') or 'primary'
    if not release_id or not artist_id:
        return 'skipped'
    if not Release.objects.filter(pk=release_id).exists() or not Artist.objects.filter(pk=artist_id).exists():
        return 'skipped'
    existing_same_credit = ReleaseArtistCredit.objects.filter(
        release_id=release_id, artist_id=artist_id, role=role
    ).first()
    if existing_same_credit:
        return 'already_present'

    credit = ReleaseArtistCredit.objects.filter(pk=snapshot.get('id')).first()
    position = snapshot.get('position') or 0
    position_taken = ReleaseArtistCredit.objects.filter(
        release_id=release_id, role=role, position=position
    ).exclude(pk=getattr(credit, 'pk', None)).exists()
    if position_taken:
        position = _next_credit_position(release_id, role)
    if credit:
        credit.release_id = release_id
        credit.artist_id = artist_id
        credit.role = role
        credit.position = position
        credit.save(update_fields=['release', 'artist', 'role', 'position'])
        return 'moved_back'

    preserve_pk = not ReleaseArtistCredit.objects.filter(pk=snapshot.get('id')).exists()
    _create_model_from_snapshot(
        ReleaseArtistCredit,
        snapshot,
        overrides={'release_id': release_id, 'artist_id': artist_id, 'role': role, 'position': position},
        preserve_pk=preserve_pk,
    )
    return 'recreated'


def _restore_release_credits(credit_snapshots, release_id):
    stats = {'recreated': 0, 'moved_back': 0, 'already_present': 0, 'skipped': 0}
    for snapshot in credit_snapshots or []:
        result = _restore_artist_credit(snapshot, release_id=release_id)
        stats[result] = stats.get(result, 0) + 1
    return stats


def _restore_certifications(certifications, release_id):
    restored = 0
    skipped = 0
    for snapshot in certifications or []:
        if not release_id or not snapshot.get('level'):
            skipped += 1
            continue
        if not Release.objects.filter(pk=release_id).exists():
            skipped += 1
            continue
        defaults = {}
        for field in Certification._meta.fields:
            key = _field_key(field)
            if key in {'id', 'release_id', 'level'}:
                continue
            if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
                continue
            if key in snapshot:
                defaults[key] = _coerce_for_field(field, snapshot[key])
        Certification.objects.update_or_create(
            release_id=release_id,
            level=snapshot['level'],
            defaults=defaults,
        )
        restored += 1
    return {'restored': restored, 'skipped': skipped}


def _restore_keeper_release_fields(keeper, snapshot):
    changed = []
    keeper_fields = snapshot.get('keeper_restorable_fields') or {}
    for field, values in keeper_fields.items():
        if not hasattr(keeper, field):
            continue
        model_field = keeper._meta.get_field(field)
        current_value = _json_field_value(model_field, getattr(keeper, field))
        if current_value == values.get('copied'):
            setattr(keeper, field, _coerce_for_field(model_field, values.get('before')))
            changed.append(field)
    if changed:
        keeper.save(update_fields=[*changed, 'updated_at'])
    return changed


def _restore_release_state(state, duplicate, keeper):
    return {
        'monthly_entries': _restore_monthly_entries(state.get('monthly_entries'), duplicate, keeper),
        'platform_entries': _restore_platform_entries(state.get('platform_entries'), duplicate, keeper),
        'credits': _restore_release_credits(state.get('release_artist_credits'), duplicate.id),
        'certifications': _restore_certifications(state.get('certifications'), duplicate.id),
    }


def _create_duplicate_release(state):
    release_snapshot = state.get('release') or {}
    release_id = release_snapshot.get('id')
    if Release.objects.filter(pk=release_id).exists():
        raise MergeUndoError(f'Release ID {release_id} already exists; undo cannot safely recreate the duplicate.')
    if not Artist.objects.filter(pk=release_snapshot.get('artist_id')).exists():
        raise MergeUndoError('The duplicate release artist no longer exists.')
    try:
        return _create_model_from_snapshot(Release, release_snapshot, preserve_pk=True)
    except IntegrityError as exc:
        raise MergeUndoError(f'Could not recreate duplicate release: {exc}') from exc


def _undo_release_merge(history):
    snapshot = history.snapshot or {}
    keeper = Release.objects.filter(pk=history.keeper_id).first()
    if keeper is None:
        raise MergeUndoError('The kept release no longer exists.')
    state = snapshot.get('release_state') or {}
    duplicate = _create_duplicate_release(state)
    result = {
        'duplicate_release_id': duplicate.id,
        'keeper_fields_restored': _restore_keeper_release_fields(keeper, snapshot),
        **_restore_release_state(state, duplicate, keeper),
    }
    normalization = snapshot.get('normalization') or {}
    result['normalization'] = _restore_normalization_rules(
        normalization.get('rule_type') or 'title',
        normalization.get('raw_values') or [],
        normalization.get('canonical_value') or '',
        normalization.get('before') or [],
    )
    chart_ids = snapshot.get('affected_chart_ids') or []
    from .cms_utils import harmonize_chart_history, recalculate_certifications
    if chart_ids:
        result['harmonization'] = harmonize_chart_history(chart_ids=chart_ids)
    else:
        result['harmonization'] = harmonize_chart_history(chart_type=snapshot.get('chart_type') or keeper.chart_type)
    recalculate_certifications(release=keeper)
    recalculate_certifications(release=duplicate)
    return result


def _remove_merge_added_aliases(primary, snapshot):
    before = set((snapshot.get('primary') or {}).get('aliases') or [])
    duplicate = snapshot.get('duplicate') or {}
    merge_added = set([duplicate.get('name'), *((duplicate.get('aliases') or []))])
    current = list(primary.aliases or [])
    next_aliases = [
        alias for alias in current
        if alias in before or alias not in merge_added
    ]
    if next_aliases != current:
        primary.aliases = next_aliases
        primary.save(update_fields=['aliases', 'updated_at'])
        return len(current) - len(next_aliases)
    return 0


def _create_duplicate_artist(snapshot):
    artist_snapshot = snapshot.get('duplicate') or {}
    artist_id = artist_snapshot.get('id')
    if Artist.objects.filter(pk=artist_id).exists():
        raise MergeUndoError(f'Artist ID {artist_id} already exists; undo cannot safely recreate the duplicate.')
    try:
        return _create_model_from_snapshot(Artist, artist_snapshot, preserve_pk=True)
    except IntegrityError as exc:
        raise MergeUndoError(f'Could not recreate duplicate artist: {exc}') from exc


def _undo_artist_direct_releases(snapshot, duplicate_artist, primary_artist):
    stats = {
        'moved_releases_back': 0,
        'recreated_releases': 0,
        'release_restores': [],
        'skipped': 0,
    }
    for item in snapshot.get('direct_releases') or []:
        state = item.get('state') or {}
        release_snapshot = state.get('release') or {}
        if item.get('action') == 'moved_release':
            release = Release.objects.filter(pk=release_snapshot.get('id')).first()
            if not release:
                stats['skipped'] += 1
                continue
            if release.artist_id == primary_artist.id:
                release.artist = duplicate_artist
                release.country = duplicate_artist.country or ''
                release.country_code = (duplicate_artist.country_code or '').strip().upper()
                release.save(update_fields=['artist', 'country', 'country_code', 'updated_at'])
                stats['moved_releases_back'] += 1
            continue

        keeper = Release.objects.filter(pk=item.get('keeper_release_id')).first()
        if keeper is None:
            stats['skipped'] += 1
            continue
        release = _create_duplicate_release(state)
        stats['recreated_releases'] += 1
        stats['release_restores'].append(_restore_release_state(state, release, keeper))
    return stats


def _undo_artist_credits(snapshot, duplicate_artist):
    stats = {'recreated': 0, 'moved_back': 0, 'already_present': 0, 'skipped': 0}
    for credit_snapshot in snapshot.get('artist_credits') or []:
        result = _restore_artist_credit(credit_snapshot, artist_id=duplicate_artist.id)
        stats[result] = stats.get(result, 0) + 1
    return stats


def _undo_artist_merge(history):
    snapshot = history.snapshot or {}
    primary = Artist.objects.filter(pk=history.keeper_id).first()
    if primary is None:
        raise MergeUndoError('The kept artist no longer exists.')
    duplicate = _create_duplicate_artist(snapshot)
    result = {
        'duplicate_artist_id': duplicate.id,
        'aliases_removed_from_keeper': _remove_merge_added_aliases(primary, snapshot),
        'direct_releases': _undo_artist_direct_releases(snapshot, duplicate, primary),
        'artist_credits': _undo_artist_credits(snapshot, duplicate),
    }
    normalization = snapshot.get('normalization') or {}
    result['normalization'] = _restore_normalization_rules(
        normalization.get('rule_type') or 'artist',
        normalization.get('raw_values') or [],
        normalization.get('canonical_value') or '',
        normalization.get('before') or [],
    )
    chart_ids = snapshot.get('affected_chart_ids') or []
    from .cms_utils import harmonize_chart_history
    if chart_ids:
        result['harmonization'] = harmonize_chart_history(chart_ids=chart_ids)
    return result


@transaction.atomic
def undo_merge_history(history, user=None):
    if history.status != MergeHistory.Status.UNDOABLE:
        raise MergeUndoError('This merge has already been undone or blocked.')
    if history.merge_type == MergeHistory.MergeType.RELEASE:
        result = _undo_release_merge(history)
    elif history.merge_type == MergeHistory.MergeType.ARTIST:
        result = _undo_artist_merge(history)
    else:
        raise MergeUndoError('Unsupported merge type.')

    history.status = MergeHistory.Status.UNDONE
    history.error = ''
    history.undone_by = user if user and user.is_authenticated else None
    history.undone_at = timezone.now()
    history.save(update_fields=['status', 'error', 'undone_by', 'undone_at'])
    from .cms_utils import bump_public_revision
    bump_public_revision()
    return result
