"""
Hard-delete all duplicate Release records across the database.

Two releases are duplicates when lower(title) + chart_type match.
The keeper is chosen as: cover_image > most MonthlyChartEntry rows > lowest id.
All other matching records have their chart entries migrated to the keeper,
then are permanently deleted (not archived).

Points are NOT summed for conflicting entries — the keeper's data wins.

Usage:
    python manage.py purge_release_duplicates --dry-run
    python manage.py purge_release_duplicates
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from charts.models import (
    AuditLog,
    Certification,
    MonthlyChartEntry,
    PlatformChartEntry,
    Release,
    ReleaseArtistCredit,
)
from charts.cms_utils import recalculate_certifications


def _safe(s):
    return str(s or "").encode("ascii", "replace").decode("ascii")


def _pick_keeper(releases):
    """Return the release that should be kept."""
    # Prefer: has cover image > most chart entries > lowest id
    entry_counts = {
        r.id: MonthlyChartEntry.objects.filter(release=r).count()
        for r in releases
    }
    return max(
        releases,
        key=lambda r: (bool(r.cover_image), entry_counts[r.id], -r.id),
    )


def _migrate_and_delete(dup, keeper, dry_run):
    """Move chart entries from dup to keeper, then hard-delete dup."""
    reassigned = dropped = 0

    for dup_entry in list(MonthlyChartEntry.objects.filter(release=dup)):
        conflict = MonthlyChartEntry.objects.filter(
            chart_id=dup_entry.chart_id,
            platform_id=dup_entry.platform_id,
            release=keeper,
        ).exists()
        if conflict:
            dropped += 1
            if not dry_run:
                dup_entry.delete()
        else:
            reassigned += 1
            if not dry_run:
                dup_entry.release = keeper
                dup_entry.save(update_fields=["release"])

    if not dry_run:
        PlatformChartEntry.objects.filter(release=dup).update(release=keeper)
        # Move unique artist credits
        existing = set(
            ReleaseArtistCredit.objects.filter(release=keeper)
            .values_list("artist_id", "role")
        )
        for credit in ReleaseArtistCredit.objects.filter(release=dup):
            if (credit.artist_id, credit.role) not in existing:
                ReleaseArtistCredit.objects.create(
                    release=keeper,
                    artist_id=credit.artist_id,
                    role=credit.role,
                    position=ReleaseArtistCredit.objects.filter(
                        release=keeper, role=credit.role
                    ).count(),
                )
                existing.add((credit.artist_id, credit.role))
        # Fill blank metadata on keeper from dup
        _FIELDS = [
            "cover_image", "genre", "label", "distributor", "isrc", "upc",
            "release_year", "release_date", "featured_artists", "credited_artists",
            "songwriters", "producers", "spotify_url", "apple_music_url",
            "youtube_url", "boomplay_url", "audiomack_url", "tiktok_url",
            "shazam_url", "radio_info",
        ]
        updates = []
        for f in _FIELDS:
            if getattr(dup, f) and not getattr(keeper, f):
                setattr(keeper, f, getattr(dup, f))
                updates.append(f)
        if updates:
            keeper.save(update_fields=updates + ["updated_at"])

        Certification.objects.filter(release=dup).delete()
        dup.delete()  # hard delete

    return reassigned, dropped


class Command(BaseCommand):
    help = "Hard-delete all duplicate Release records, keeping the best copy."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        prefix = "[DRY RUN] " if dry_run else ""

        # Load all non-archived releases, group by (lower_title, chart_type, artist_id).
        # Including artist_id prevents songs that merely share a title but have
        # different artists (e.g. "Baby" by The Ben vs "Baby" by Justin Bieber)
        # from being wrongly merged.
        all_releases = list(
            Release.objects.exclude(status="archived")
            .select_related("artist")
            .order_by("id")
        )

        groups = defaultdict(list)
        for r in all_releases:
            key = (r.title.strip().lower(), r.chart_type, r.artist_id)
            groups[key].append(r)

        duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}

        if not duplicate_groups:
            self.stdout.write(self.style.SUCCESS("No duplicate releases found."))
            return

        self.stdout.write(
            f"\n{prefix}Found {len(duplicate_groups)} duplicate group(s):\n"
        )

        total_deleted = 0
        affected_keepers = set()

        def _run():
            nonlocal total_deleted

            for (title_lower, ct), releases in sorted(duplicate_groups.items()):
                keeper = _pick_keeper(releases)
                dups = [r for r in releases if r.id != keeper.id]

                entry_counts = {
                    r.id: MonthlyChartEntry.objects.filter(release=r).count()
                    for r in releases
                }

                self.stdout.write(
                    f"{prefix}  [{ct}] {_safe(title_lower)!r}  "
                    f"({len(dups)} dup(s) -> keeper id={keeper.id})"
                )
                for r in releases:
                    flag = "KEEP" if r.id == keeper.id else "DELETE"
                    self.stdout.write(
                        f"{prefix}    [{flag}] id={r.id} "
                        f"title={_safe(r.title)!r} "
                        f"artist={_safe(r.artist.name)!r} "
                        f"entries={entry_counts[r.id]} "
                        f"img={bool(r.cover_image)}"
                    )

                for dup in dups:
                    r, d = _migrate_and_delete(dup, keeper, dry_run)
                    self.stdout.write(
                        f"{prefix}      -> id={dup.id} deleted: "
                        f"entries_moved={r} entries_dropped={d}"
                    )
                    total_deleted += 1

                affected_keepers.add(keeper.id)

        if dry_run:
            with transaction.atomic():
                _run()
                transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING(
                f"\nDry run -- {total_deleted} record(s) would be deleted. Nothing saved."
            ))
        else:
            with transaction.atomic():
                _run()

            self.stdout.write("\nRecalculating certifications...")
            for rid in affected_keepers:
                try:
                    recalculate_certifications(release=Release.objects.get(pk=rid))
                except Release.DoesNotExist:
                    pass

            try:
                AuditLog.objects.create(
                    action="purge_release_duplicates",
                    module="releases",
                    object_type="Release",
                    object_id="",
                    object_repr=f"Hard-deleted {total_deleted} duplicate releases",
                    old_value={},
                    new_value={
                        "groups": len(duplicate_groups),
                        "deleted": total_deleted,
                        "timestamp": timezone.now().isoformat(),
                    },
                    reason="purge_release_duplicates management command",
                    user=None, ip_address=None, user_agent="management-command",
                )
            except Exception:
                pass

            self.stdout.write(self.style.SUCCESS(
                f"\nDone. {total_deleted} duplicate release(s) permanently deleted."
            ))
