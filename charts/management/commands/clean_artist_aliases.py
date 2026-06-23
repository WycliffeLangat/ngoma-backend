"""
One-time cleanup: remove pipe-separated artist aliases from the database.

The pipe character was used internally to track artist aliases
(e.g. "Toxic Lyrikali|Countree Hype"), but it should never appear in
artist names. This command:

  1. Finds every Artist whose name contains "|"
  2. Strips everything from "|" onwards to get the canonical name
  3. If a clean-named artist already exists, relinks all releases and
     chart entries to that canonical record and deletes the alias artist
  4. Otherwise renames the artist in place
  5. Also clears display_name values that contain "|"

Run dry-run first to preview changes:
  python manage.py clean_artist_aliases --dry-run

Then apply:
  python manage.py clean_artist_aliases
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from charts.models import Artist, Release


class Command(BaseCommand):
    help = "Remove pipe-separated aliases from artist names and merge duplicates"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        prefix = "[DRY RUN] " if dry_run else ""

        changed = 0

        with transaction.atomic():
            # ── 1. Clean display_name fields that contain "|" ──────────────
            dirty_display = Artist.objects.filter(display_name__contains="|")
            for artist in dirty_display:
                clean = artist.display_name.split("|")[0].strip()
                self.stdout.write(
                    f"{prefix}Clean display_name: id={artist.id} "
                    f"{repr(artist.display_name)} -> {repr(clean)}"
                )
                if not dry_run:
                    artist.display_name = clean
                    artist.save(update_fields=["display_name"])
                changed += 1

            # ── 2. Fix artist names that contain "|" ───────────────────────
            pipe_artists = Artist.objects.filter(name__contains="|")
            for artist in pipe_artists:
                clean_name = artist.name.split("|")[0].strip()

                # Is there already a canonical artist with the clean name?
                canonical = (
                    Artist.objects.filter(name__iexact=clean_name)
                    .exclude(id=artist.id)
                    .first()
                )

                if canonical:
                    releases = Release.objects.filter(artist=artist)
                    self.stdout.write(
                        f"{prefix}Merge id={artist.id} {repr(artist.name)} "
                        f"-> canonical id={canonical.id} {repr(canonical.name)} "
                        f"({releases.count()} release(s))"
                    )
                    if not dry_run:
                        releases.update(artist=canonical)
                        artist.delete()
                else:
                    self.stdout.write(
                        f"{prefix}Rename id={artist.id} {repr(artist.name)} "
                        f"-> {repr(clean_name)}"
                    )
                    if not dry_run:
                        artist.name = clean_name
                        artist.save(update_fields=["name"])

                changed += 1

            if dry_run:
                transaction.set_rollback(True)

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run — {changed} change(s) previewed, nothing saved"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done — {changed} artist record(s) cleaned"))
