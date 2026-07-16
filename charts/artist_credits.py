import re


ARTIST_SEPARATOR_RE = re.compile(
    r'\s*(?:,|&|\b(?:and|x|with|feat|featuring|ft)\b\.?)\s*',
    re.IGNORECASE,
)
FEATURE_SEPARATOR_RE = re.compile(
    r'\s*\b(?:feat|featuring|ft)\b\.?\s*',
    re.IGNORECASE,
)
PRIMARY_SEPARATOR_RE = re.compile(
    r'\s*(?:,|&|\b(?:and|x|with)\b)\s*',
    re.IGNORECASE,
)
ARTIST_NAME_SEPARATOR_RE = re.compile(
    r'[,/&]|\b(?:and|x|with|feat|featuring|ft)\b\.?',
    re.IGNORECASE,
)
PROTECTED_ARTIST_TYPES = {'group', 'band', 'duo'}

# Separators are part of these canonical act names, not collaboration syntax.
# An editorially managed Artist marked as a group/band/duo is also protected.
NON_COLLABORATION_ARTIST_NAMES = {
    'earth, wind & fire',
    'florence & the machine',
    'mumford & sons',
    'papi clever & dorcas',
    'simon & garfunkel',
    'stanley & the turbines',
    'tyler, the creator',
    'years & years',
}


def artist_name_has_separator(value):
    return bool(ARTIST_NAME_SEPARATOR_RE.search(str(value or '').strip()))


def should_preserve_registered_artist_name(value, artist=None):
    value = str(value or '').strip()
    if not value:
        return False
    if value.casefold() in NON_COLLABORATION_ARTIST_NAMES:
        return True
    if not artist:
        return False
    artist_type = str(getattr(artist, 'artist_type', '') or '').strip().casefold()
    return artist_type in PROTECTED_ARTIST_TYPES or artist_name_has_separator(value)


def unique_names(names):
    result = []
    seen = set()
    for value in names:
        name = str(value or '').strip()
        key = name.casefold()
        if name and key not in seen:
            result.append(name)
            seen.add(key)
    return result


def split_artist_names(value, preserve_name=False):
    value = str(value or '').strip()
    if preserve_name or value.casefold() in NON_COLLABORATION_ARTIST_NAMES:
        return unique_names([value])
    return unique_names(ARTIST_SEPARATOR_RE.split(value))


def parse_artist_credit(value, preserve_name=False):
    """Return ordered primary and featured names from one artist credit.

    ``ft.``, ``feat.`` and ``featuring`` start featured credits. Ampersands,
    commas, ``and``, ``x`` and ``with`` describe equal primary credits. Every
    returned artist receives the release's full public chart points.
    """
    value = str(value or '').strip()
    if not value:
        return [], []
    if preserve_name or value.casefold() in NON_COLLABORATION_ARTIST_NAMES:
        return [value], []

    parts = FEATURE_SEPARATOR_RE.split(value, maxsplit=1)
    primary = unique_names(PRIMARY_SEPARATOR_RE.split(parts[0]))
    featured = split_artist_names(parts[1]) if len(parts) > 1 else []
    primary_keys = {name.casefold() for name in primary}
    featured = [name for name in featured if name.casefold() not in primary_keys]
    return primary, featured


def format_artist_list(names):
    names = unique_names(names)
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return ' & '.join(names)
    return f"{', '.join(names[:-1])} & {names[-1]}"


def _credit_rows(release, role):
    rows = list(release.artist_credits.all())
    return sorted((row for row in rows if row.role == role), key=lambda row: (row.position, row.pk))


def _clean_display_name(name):
    # Pipe is used internally as an alias separator (e.g. "Toxic Lyrikali|Countree Hype")
    # but must never appear in user-facing credits — keep only the canonical name.
    return str(name or '').split('|')[0].strip()


def release_credit_artists(release, entry_featured=''):
    primary_artists = [row.artist for row in _credit_rows(release, 'primary')]
    if not primary_artists:
        primary_artists = [release.artist]

    featured_artists = [row.artist for row in _credit_rows(release, 'featured')]
    featured_names = unique_names([
        *(_clean_display_name(artist.display_name or artist.name) for artist in featured_artists),
        *split_artist_names(release.featured_artists),
        *split_artist_names(entry_featured),
    ])
    primary_names = unique_names(
        _clean_display_name(artist.display_name or artist.name)
        for artist in primary_artists
    )
    primary_keys = {name.casefold() for name in primary_names}
    featured_names = [name for name in featured_names if name.casefold() not in primary_keys]
    return primary_artists, featured_artists, primary_names, featured_names


def release_credit_payload(release, entry_featured=''):
    primary_artists, featured_artists, primary_names, featured_names = release_credit_artists(
        release, entry_featured=entry_featured
    )
    primary_credit = format_artist_list(primary_names)
    featured_credit = format_artist_list(featured_names)
    artist_credit = f'{primary_credit} ft. {featured_credit}' if featured_credit else primary_credit
    return {
        'primary_artists': primary_artists,
        'featured_artists': featured_artists,
        'primary_artist_names': primary_names,
        'featured_artist_names': featured_names,
        'primary_artist_credit': primary_credit,
        'featured_artist_credit': featured_credit,
        'artist_credit': artist_credit,
    }
