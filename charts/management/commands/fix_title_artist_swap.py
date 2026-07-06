"""
Detect and fix releases where title and artist got swapped during ingestion.

split_song_artist() in charts/pipeline.py assumes every raw row is formatted
"Title - Artist" and splits on the first " - " accordingly. If a source
platform/week's raw data was instead formatted "Artist - Title" (e.g.
"Drake - Janice STFU"), that produces a release titled "Drake" credited to a
bogus new artist named after the real song ("Janice STFU"). This command
detects that pattern (a release title that exactly matches a *different*
artist's name) and repairs it: renames the release to the real title,
re-credits it to the real artist, and merges it into an existing correct
release if one already exists (otherwise renames it in place). The bogus
"artist" is removed once it has no releases left.

Usage:
    python manage.py fix_title_artist_swap --dry-run
    python manage.py fix_title_artist_swap --apply
    python manage.py fix_title_artist_swap --apply --artist "Drake"
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from charts.models import Artist, AuditLog, Release, ReleaseArtistCredit
from charts.cms_utils import recalculate_certifications
from charts.management.commands.merge_duplicate_releases import (
    _merge_chart_entries,
    _merge_platform_chart_entries,
    _merge_artist_credits,
    _merge_metadata,
    _merge_certifications,
)


class Command(BaseCommand):
    help = (
        "Detect releases whose title is actually another artist's name (a "
        "title/artist swap from ingestion) and fix them."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument("--dry-run", action="store_true", help="Preview without modifying the database")
        group.add_argument("--apply", action="store_true", help="Apply the fixes explicitly")
        parser.add_argument(
            "--artist", default="",
            help="Only fix swaps where the real artist's name matches this (case-insensitive).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or not options["apply"]
        artist_filter = options["artist"].strip().lower()
        mode_label = "DRY RUN" if dry_run else "APPLY"
        self.stdout.write(self.style.WARNING(f"\n[{mode_label}] Scanning for title/artist swaps...\n"))

        artists_by_id = {a.id: a for a in Artist.objects.all()}
        artist_id_by_name = {a.name.strip().lower(): a.id for a in artists_by_id.values()}

        suspects = []
        for r in Release.objects.exclude(status="archived").select_related("artist"):
            real_artist_id = artist_id_by_name.get(r.title.strip().lower())
            if not real_artist_id or real_artist_id == r.artist_id:
                continue
            if artist_filter and artists_by_id[real_artist_id].name.strip().lower() != artist_filter:
                continue
            suspects.append(r)

        self.stdout.write(f"  Found {len(suspects)} suspected swap(s)\n")

        fixed = merged = artists_pruned = 0

        for dup in suspects:
            real_artist = artists_by_id[artist_id_by_name[dup.title.strip().lower()]]
            bogus_artist = dup.artist
            real_title = bogus_artist.name
            real_canonical = real_title.strip().lower()

            existing = (
                Release.objects.filter(artist=real_artist, canonical_title=real_canonical, chart_type=dup.chart_type)
                .exclude(pk=dup.pk)
                .first()
            )

            if existing:
                self.stdout.write(
                    f"  [{dup.id}] {dup.title!r} / {dup.artist.name!r}  ->  merge into existing "
                    f"release id={existing.id} ({real_title!r} / {real_artist.name!r})"
                )
                if not dry_run:
                    with transaction.atomic():
                        _merge_chart_entries(dup, existing, dry_run=False)
                        _merge_platform_chart_entries(dup, existing, dry_run=False)
                        _merge_artist_credits(dup, existing, dry_run=False)
                        _merge_metadata(dup, existing, dry_run=False)
                        _merge_certifications(dup, existing, dry_run=False)
                        AuditLog.objects.create(
                            action="fixed_title_artist_swap_merged", module="releases",
                            object_type="Release", object_id=str(existing.pk), object_repr=str(existing)[:255],
                            old_value={"bad_release_id": dup.pk, "bad_title": dup.title, "bad_artist": bogus_artist.name},
                            new_value={}, reason="Title/artist swap detected and merged into existing correct release",
                        )
                        dup.delete()
                merged += 1
            else:
                self.stdout.write(
                    f"  [{dup.id}] {dup.title!r} / {dup.artist.name!r}  ->  rename in place to "
                    f"{real_title!r} / {real_artist.name!r}"
                )
                if not dry_run:
                    with transaction.atomic():
                        old_title, old_artist_name = dup.title, dup.artist.name
                        dup.title = real_title
                        dup.canonical_title = real_canonical
                        dup.artist = real_artist
                        dup.save(update_fields=["title", "canonical_title", "artist", "updated_at"])
                        if ReleaseArtistCredit.objects.filter(release=dup, artist=real_artist, role="primary").exists():
                            ReleaseArtistCredit.objects.filter(release=dup, artist=bogus_artist).delete()
                        else:
                            ReleaseArtistCredit.objects.filter(release=dup, artist=bogus_artist).update(artist=real_artist)
                        AuditLog.objects.create(
                            action="fixed_title_artist_swap", module="releases",
                            object_type="Release", object_id=str(dup.pk), object_repr=str(dup)[:255],
                            old_value={"title": old_title, "artist": old_artist_name},
                            new_value={"title": real_title, "artist": real_artist.name},
                            reason="Title/artist swap detected during ingestion (split_song_artist assumed wrong order)",
                        )
                fixed += 1

            if not dry_run and not Release.objects.filter(artist=bogus_artist).exists():
                bogus_artist.delete()
                artists_pruned += 1

        if not dry_run and (fixed or merged):
            recalculate_certifications()

        verb = "Would fix" if dry_run else "Fixed"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb}: {fixed} renamed in place, {merged} merged into an existing release, "
            f"{artists_pruned} bogus artist(s) removed.\n"
        ))
