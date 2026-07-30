"""Apply the internet-researched metadata workbook (scripts/metadata_research_june2026.json)
to Artist and Release records.

Source: NgomaCharts_Metadata_Research.xlsx, prepared 2026-07-30 to fill gaps found by the
June 2026 chart-entries data-quality audit (72 artists, 50 songs, 50 albums).

Safety rules, matching the workbook's own "do not overwrite" guidance:
  - Only fills fields that are CURRENTLY BLANK on the live record. Never overwrites an
    existing value, even if the research disagrees with it.
  - Never touches Artist.verified. The workbook's "Recommended Verified" column is a
    research recommendation, not a confirmed identity match — leave that toggle to a human
    reviewing each profile in the CMS.
  - Never merges artists. The Papa Nyosto (#1043 -> #1064) duplicate is handled separately
    via the CMS's own Duplicate Review / merge action, which correctly moves release credits
    and logs the merge (see ArtistViewSet.merge in cms_views.py) -- this command does not
    reimplement that.
  - Defaults to --dry-run reporting; nothing is written unless --apply is passed.
"""
import json
import os

from django.core.management.base import BaseCommand
from django.db import transaction

from charts.models import Artist, Release

DEFAULT_PATH = os.path.join("scripts", "metadata_research_june2026.json")

ARTIST_FIELDS = ["country", "country_code", "city_region", "genre", "biography"]
RELEASE_COMMON_FIELDS = ["genre", "label", "distributor", "country", "country_code"]


class Command(BaseCommand):
    help = "Backfill blank Artist/Release fields from the researched metadata workbook."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=DEFAULT_PATH, help="Path to the research JSON file.")
        parser.add_argument("--apply", action="store_true", help="Write changes. Without this flag, only reports what would change.")

    def handle(self, *args, **options):
        path = options["path"]
        apply_changes = options["apply"]

        with open(path, encoding="utf-8") as f:
            payload = json.load(f)

        artist_changes, artist_misses = self._plan_artists(payload["artists"])
        song_changes, song_misses = self._plan_releases(payload["songs"], "song")
        album_changes, album_misses = self._plan_releases(payload["albums"], "album")

        self._report("Artists", artist_changes, artist_misses)
        self._report("Songs", song_changes, song_misses)
        self._report("Albums", album_changes, album_misses)

        if apply_changes:
            with transaction.atomic():
                if artist_changes:
                    objs = [c["obj"] for c in artist_changes]
                    Artist.objects.bulk_update(objs, ARTIST_FIELDS, batch_size=200)
                if song_changes or album_changes:
                    objs = [c["obj"] for c in (song_changes + album_changes)]
                    fields = sorted({f for c in (song_changes + album_changes) for f in c["fields"]})
                    Release.objects.bulk_update(objs, fields, batch_size=200)
            self.stdout.write(self.style.SUCCESS(
                f"\nAPPLIED: {len(artist_changes)} artist(s), {len(song_changes)} song(s), {len(album_changes)} album(s) updated."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN -- no changes written. Re-run with --apply to save these."
            ))

        self.stdout.write(
            "\nNot automated by this command (needs a human step in the CMS):\n"
            "  - Verified toggle for any artist -- confirm identity in the CMS, then check the box.\n"
            "  - Papa Nyosto duplicate (#1043 -> #1064) -- resolve via Duplicate Review's merge action.\n"
        )

    def _plan_artists(self, rows):
        changes, misses = [], []
        by_id = {a.id: a for a in Artist.objects.filter(id__in=[r["id"] for r in rows])}
        for r in rows:
            artist = by_id.get(r["id"])
            if artist is None:
                misses.append(f"#{r['id']} {r['name']} -- no longer exists")
                continue
            fields = {}
            for field in ARTIST_FIELDS:
                current = getattr(artist, field, "")
                new = r.get(field, "")
                if not (current or "").strip() and (new or "").strip():
                    fields[field] = new
            if fields:
                for k, v in fields.items():
                    setattr(artist, k, v)
                changes.append({"obj": artist, "fields": list(fields.keys()), "label": f"#{r['id']} {r['name']}", "detail": fields})
        return changes, misses

    def _plan_releases(self, rows, kind):
        changes, misses = [], []
        by_id = {rel.id: rel for rel in Release.objects.filter(id__in=[r["id"] for r in rows])}
        extra_fields = ["songwriters", "producers"] if kind == "song" else ["number_of_tracks"]
        for r in rows:
            release = by_id.get(r["id"])
            if release is None:
                misses.append(f"#{r['id']} {r['title']} -- no longer exists")
                continue
            fields = {}
            for field in RELEASE_COMMON_FIELDS + extra_fields:
                if field not in r:
                    continue
                current = getattr(release, field, None)
                new = r.get(field)
                is_blank_current = current in (None, "", 0) if field == "number_of_tracks" else not str(current or "").strip()
                has_new = new not in (None, "") if field == "number_of_tracks" else bool(str(new or "").strip())
                if is_blank_current and has_new:
                    fields[field] = new
            # release_date / release_year handled together, tied to release_year presence
            if r.get("release_year") and not release.release_year:
                fields["release_year"] = r["release_year"]
                if r.get("release_date") and not release.release_date:
                    fields["release_date"] = r["release_date"]
            if fields:
                for k, v in fields.items():
                    setattr(release, k, v)
                changes.append({"obj": release, "fields": list(fields.keys()), "label": f"#{r['id']} {r['title']} - {r['artist']}", "detail": fields})
        return changes, misses

    def _report(self, title, changes, misses):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{title}: {len(changes)} record(s) to update, {len(misses)} not found"))
        for c in changes[:25]:
            self.stdout.write(f"  {c['label']}: {', '.join(c['fields'])}")
        if len(changes) > 25:
            self.stdout.write(f"  ...and {len(changes) - 25} more.")
        for m in misses:
            self.stdout.write(self.style.ERROR(f"  MISSING RECORD: {m}"))
