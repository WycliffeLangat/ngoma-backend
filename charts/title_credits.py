"""Promote explicit title feature credits into stored release artist links."""
import re

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .artist_credits import format_artist_list, split_artist_names, unique_names


def split_protected_credit(credit, protected_names):
    placeholders = {}
    for index, name in enumerate(sorted(protected_names, key=len, reverse=True)):
        token = f'NGOMAPROTECTED{index}TOKEN'
        credit, count = re.subn(
            r'(?<!\w)' + re.escape(name) + r'(?!\w)', token, credit, flags=re.I,
        )
        if count:
            placeholders[token] = name
    return [placeholders.get(name, name) for name in split_artist_names(credit)]


def title_featured_names(title, protected_names=()):
    # Only explicit credits: ordinary titles such as "With You" aren't names.
    pattern = r'(?:[\[(]\s*(?:featuring|feat\.?|ft\.?|with)\s+|\s+(?:featuring|feat\.?|ft\.?)\s+)([^\[\]()]+)'
    names = []
    for match in re.finditer(pattern, str(title or ''), re.I):
        credit = re.split(r'\s+[-–—]\s+', match.group(1))[0].strip()
        names.extend(split_protected_credit(credit, protected_names))
    # Truncated source titles cannot identify the final artist reliably.
    return unique_names(name for name in names if not re.search(r'\.{3}|…', name) and re.search(r'\w', name))


@transaction.atomic
def sync_title_credits(release):
    from .models import Artist, Release, ReleaseArtistCredit, MonthlyChartEntry, RegionalChartEntry
    from .pipeline import get_or_create_artist
    from .artist_credits import should_preserve_registered_artist_name

    if not title_featured_names(release.title):
        return False
    # Serialize concurrent imports of the same release.
    Release.objects.select_for_update().get(pk=release.pk)
    artists = list(Artist.objects.exclude(status='archived').only('id', 'name', 'display_name', 'aliases', 'artist_type'))
    protected = [name for a in artists for name in (a.name, a.display_name, *(a.aliases or [])) if name and should_preserve_registered_artist_name(name, a)]
    names = title_featured_names(release.title, protected)
    lookup = {}
    for artist in artists:
        for name in (artist.name, artist.display_name):
            if name:
                lookup.setdefault(name.casefold(), artist)
    for artist in artists:
        for name in artist.aliases or []:
            lookup.setdefault(str(name).casefold(), artist)
    existing = list(release.artist_credits.select_related('artist'))
    primary_ids = {c.artist_id for c in existing if c.role == 'primary'} or {release.artist_id}
    featured = [c.artist for c in existing if c.role == 'featured']
    seen = primary_ids | {a.id for a in featured}
    changed = False
    for name in names:
        artist = lookup.get(name.casefold()) or get_or_create_artist(name)
        if artist.id in seen:
            continue
        ReleaseArtistCredit.objects.get_or_create(
            release=release, artist=artist, role='featured',
            defaults={'position': len(featured)},
        )
        featured.append(artist)
        seen.add(artist.id)
        changed = True
    text = format_artist_list(unique_names([
        *split_protected_credit(release.featured_artists, protected),
        *(a.display_name or a.name for a in featured),
    ]))
    if release.featured_artists != text:
        Release.objects.filter(pk=release.pk).update(featured_artists=text, updated_at=timezone.now())
        release.featured_artists = text
        changed = True
    # Preserve entry-specific credits while filling every historical snapshot.
    for model in (MonthlyChartEntry, RegionalChartEntry):
        for entry in model.objects.filter(release=release).only('id', 'featured_artists'):
            credit = format_artist_list(unique_names([
                *split_protected_credit(entry.featured_artists, protected),
                *split_protected_credit(text, protected),
            ]))
            if entry.featured_artists != credit:
                model.objects.filter(pk=entry.pk).update(featured_artists=credit)
                changed = True
    release._prefetched_objects_cache = {}
    return changed


@receiver(post_save, sender='charts.Release', dispatch_uid='charts.title_featured_credits')
def release_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_title_credits(instance)
