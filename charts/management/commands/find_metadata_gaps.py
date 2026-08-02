"""Find Artist/Release records with blank enrichment fields and dump them to a
queue JSON that a research pass can fill in, then apply via
`apply_researched_metadata`.

This is the detection half of the auto-enrichment pipeline: it never touches
the internet or writes any Artist/Release field itself. It only answers
"which records are missing the fields apply_researched_metadata knows how to
fill?" Re-running it is always safe -- a record drops out of the queue on its
own once its fields are filled, so the same sweep naturally covers records
old and new without any "last run" bookkeeping.

Field list and exclusions mirror the completeness checks in cms_alerts.py
(artist-profile-completeness / release-metadata-completeness) and every text
field apply_researched_metadata.py knows how to write -- everything that
makes a fully-detailed record richer than a bare-bones one, short of binary
image files (Artist.image / Release.cover_image need an actual uploaded file,
not a researched value, so they're out of scope here and stay flagged for
manual upload in the CMS).
"""
import json
import os
from datetime import datetime, timezone

from django.core.management.base import BaseCommand
from django.db.models import Q

from charts.models import Artist, Release

DEFAULT_PATH = os.path.join("scripts", "metadata_gap_queue.json")
DEFAULT_LIMIT = 75

GENERIC_ARTIST_EXEMPTIONS = {"various artists"}

ARTIST_FIELDS = [
    "country", "country_code", "city_region", "genre", "biography",
    "spotify_url", "apple_music_url", "youtube_url", "boomplay_url",
    "audiomack_url", "tiktok_url", "instagram_url", "x_url", "facebook_url", "website_url",
]
RELEASE_COMMON_FIELDS = [
    "genre", "label", "distributor", "country", "country_code",
    "spotify_url", "apple_music_url", "boomplay_url", "audiomack_url",
    "youtube_url", "tiktok_url", "shazam_url",
]
RELEASE_EXTRA_FIELDS = {
    "singles": ["songwriters", "producers", "isrc"],
    "albums": ["number_of_tracks", "upc"],
}


class Command(BaseCommand):
    help = "Dump Artist/Release records missing enrichable fields to a research queue JSON."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=DEFAULT_PATH, help="Where to write the queue JSON.")
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help="Max records per entry type in one queue (keeps a single research pass a manageable size).",
        )

    def handle(self, *args, **options):
        path = options["path"]
        limit = options["limit"]

        artists = self._artist_queue(limit)
        songs = self._release_queue("singles", limit)
        albums = self._release_queue("albums", limit)

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artists": artists,
            "songs": songs,
            "albums": albums,
        }

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(
            f"Queued {len(artists)} artist(s), {len(songs)} song(s), {len(albums)} album(s) -> {path}"
        ))
        if not (artists or songs or albums):
            self.stdout.write("Nothing missing enrichable fields right now.")

    def _artist_queue(self, limit):
        blank = Q()
        for field in ARTIST_FIELDS:
            blank |= Q(**{field: ""})
        qs = Artist.objects.exclude(status="archived").filter(blank)
        for name in GENERIC_ARTIST_EXEMPTIONS:
            qs = qs.exclude(name__iexact=name)

        rows = []
        for artist in qs.order_by("name")[:limit]:
            missing = [f for f in ARTIST_FIELDS if not (getattr(artist, f) or "").strip()]
            rows.append({"id": artist.id, "name": artist.name, "missing_fields": missing})
        return rows

    def _release_queue(self, chart_type, limit):
        extra_fields = RELEASE_EXTRA_FIELDS[chart_type]

        blank = Q()
        for field in RELEASE_COMMON_FIELDS:
            blank |= Q(**{field: ""})
        for field in extra_fields:
            if field == "number_of_tracks":
                blank |= Q(**{f"{field}__isnull": True})
            else:
                blank |= Q(**{field: ""})
        blank |= Q(release_year__isnull=True) | Q(release_date__isnull=True)

        qs = (
            Release.objects.exclude(status="archived")
            .filter(chart_type=chart_type)
            .filter(blank)
            .select_related("artist")
        )

        rows = []
        for release in qs.order_by("title")[:limit]:
            missing = [f for f in RELEASE_COMMON_FIELDS if not (getattr(release, f) or "").strip()]
            for field in extra_fields:
                value = getattr(release, field)
                is_blank = value in (None, "", 0) if field == "number_of_tracks" else not (value or "").strip()
                if is_blank:
                    missing.append(field)
            if not release.release_year:
                missing.append("release_year")
            if not release.release_date:
                missing.append("release_date")
            rows.append({
                "id": release.id,
                "title": release.title,
                "artist": release.artist.name,
                "chart_type": chart_type,
                "missing_fields": missing,
            })
        return rows
