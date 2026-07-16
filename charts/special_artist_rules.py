from django.db.models import Q
from django.utils.text import slugify

from .artist_credits import unique_names


VESTINE_DORCAS_NAME = "Vestine & Dorcas"
VESTINE_DORCAS_ALIASES = {
    "vestine & dorcas",
    "vestine",
    "dorcas",
}
VESTINE_DORCAS_ALLOWED_TITLES = {
    "yebo (nitawale)",
    "emmanuel",
}


class SpecialArtistCreditError(ValueError):
    pass


def normalize_key(value):
    return str(value or "").strip().casefold()


def title_allows_vestine_dorcas(title):
    return normalize_key(title) in VESTINE_DORCAS_ALLOWED_TITLES


def name_is_vestine_dorcas_alias(name):
    return normalize_key(name) in VESTINE_DORCAS_ALIASES


def artist_is_vestine_dorcas_alias(artist):
    if not artist:
        return False
    names = [artist.name, artist.display_name, *(artist.aliases or [])]
    return any(name_is_vestine_dorcas_alias(name) for name in names)


def _unique_slug(model, text):
    base = slugify(text)[:80] or "artist"
    slug = base
    index = 2
    while model.objects.filter(slug=slug).exists():
        suffix = f"-{index}"
        slug = f"{base[:100 - len(suffix)]}{suffix}"
        index += 1
    return slug


def get_or_create_vestine_dorcas_artist(source_artist=None):
    from .models import Artist

    group = (
        Artist.objects.filter(name__iexact=VESTINE_DORCAS_NAME).first()
        or Artist.objects.filter(display_name__iexact=VESTINE_DORCAS_NAME).first()
    )
    if group:
        updates = []
        if group.artist_type != "group":
            group.artist_type = "group"
            updates.append("artist_type")
        if group.status == "archived":
            group.status = "active"
            updates.append("status")
        if updates:
            group.save(update_fields=[*updates, "updated_at"])
        return group

    if source_artist is None:
        source_artist = (
            Artist.objects.filter(name__iexact="Vestine").first()
            or Artist.objects.filter(name__iexact="Dorcas").first()
        )
    return Artist.objects.create(
        name=VESTINE_DORCAS_NAME,
        display_name=VESTINE_DORCAS_NAME,
        slug=_unique_slug(Artist, VESTINE_DORCAS_NAME),
        artist_type="group",
        country=getattr(source_artist, "country", "") or "",
        country_code=getattr(source_artist, "country_code", "") or "",
        status="active",
    )


def vestine_dorcas_target_artist_ids():
    from .models import Artist

    return set(
        Artist.objects.filter(
            Q(name__iexact="Vestine")
            | Q(name__iexact="Dorcas")
            | Q(name__iexact=VESTINE_DORCAS_NAME)
            | Q(display_name__iexact=VESTINE_DORCAS_NAME)
        ).values_list("id", flat=True)
    )


def clean_vestine_dorcas_credit_names(title, primary_names, featured_names, strict=True):
    allowed = title_allows_vestine_dorcas(title)
    saw_target = False
    next_primary = []
    next_featured = []

    for name in primary_names or []:
        if name_is_vestine_dorcas_alias(name):
            saw_target = True
            if allowed:
                next_primary.append(VESTINE_DORCAS_NAME)
            continue
        next_primary.append(name)

    for name in featured_names or []:
        if name_is_vestine_dorcas_alias(name):
            saw_target = True
            if allowed and VESTINE_DORCAS_NAME not in next_primary:
                next_featured.append(VESTINE_DORCAS_NAME)
            continue
        next_featured.append(name)

    next_primary = unique_names(next_primary)
    primary_keys = {normalize_key(name) for name in next_primary}
    next_featured = unique_names(
        name for name in next_featured if normalize_key(name) not in primary_keys
    )

    if saw_target and not allowed and strict and not next_primary:
        allowed_titles = "Yebo (Nitawale) and Emmanuel"
        raise SpecialArtistCreditError(
            f"{VESTINE_DORCAS_NAME} can only be credited on {allowed_titles}. "
            "This row has no other primary artist to keep."
        )
    return next_primary, next_featured


def clean_vestine_dorcas_credit_ids(title, primary_ids, featured_ids):
    primary_ids = list(dict.fromkeys(primary_ids or []))
    featured_ids = list(dict.fromkeys(featured_ids or []))
    target_ids = vestine_dorcas_target_artist_ids()
    target_in_primary = [artist_id for artist_id in primary_ids if artist_id in target_ids]
    target_in_featured = [artist_id for artist_id in featured_ids if artist_id in target_ids]
    if not target_in_primary and not target_in_featured:
        return primary_ids, featured_ids

    if not title_allows_vestine_dorcas(title):
        raise SpecialArtistCreditError(
            f"{VESTINE_DORCAS_NAME} can only be credited on Yebo (Nitawale) and Emmanuel."
        )

    from .models import Artist

    source_artist = Artist.objects.filter(id__in=[*target_in_primary, *target_in_featured]).first()
    group = get_or_create_vestine_dorcas_artist(source_artist=source_artist)

    def replace(ids):
        next_ids = []
        for artist_id in ids:
            next_ids.append(group.id if artist_id in target_ids else artist_id)
        return list(dict.fromkeys(next_ids))

    primary_ids = replace(primary_ids)
    primary_set = set(primary_ids)
    featured_ids = [artist_id for artist_id in replace(featured_ids) if artist_id not in primary_set]
    return primary_ids, featured_ids


def format_credit_error(error):
    return str(error)
