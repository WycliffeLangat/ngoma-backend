from .artist_credits import release_credit_payload


def _file_url(request, field):
    if not field:
        return ""
    try:
        return request.build_absolute_uri(field.url)
    except (AttributeError, ValueError):
        return ""


def _add(media, seen, url, kind, title="", entity_id=None, entity_type="", caption=""):
    if not url or url in seen:
        return
    seen.add(url)
    media.append({
        "url": url,
        "kind": kind,
        "title": title,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "caption": caption or title,
    })


def _gallery_url(item):
    if isinstance(item, str):
        return item, ""
    if not isinstance(item, dict):
        return "", ""
    return (
        item.get("url") or item.get("src") or item.get("image") or item.get("cover_image") or "",
        item.get("caption") or item.get("title") or "",
    )


def news_media_payload(request, article, artists=(), releases=()):
    """Return relevant image candidates for a news article.

    Only explicit article relationships are used. Text mentions are not scanned
    for images because names and titles can collide with unrelated records.
    """
    media = []
    seen = set()

    related_release = getattr(article, "related_release", None)
    if related_release:
        _add(
            media, seen, _file_url(request, related_release.cover_image),
            "release_cover", related_release.title, related_release.id, "release",
        )
        for artist in release_credit_payload(related_release)["primary_artists"]:
            _add(
                media, seen, _file_url(request, artist.image),
                "artist_image", artist.display_name or artist.name, artist.id, "artist",
            )

    related_artist = getattr(article, "related_artist", None)
    if related_artist:
        _add(
            media, seen, _file_url(request, related_artist.image),
            "artist_image", related_artist.display_name or related_artist.name,
            related_artist.id, "artist",
        )

    for item in article.gallery or []:
        url, caption = _gallery_url(item)
        _add(media, seen, url, "gallery", caption, caption=caption)

    _add(media, seen, _file_url(request, article.cover_image), "article_cover", article.title)
    return media
