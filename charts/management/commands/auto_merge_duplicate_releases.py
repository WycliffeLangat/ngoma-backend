"""
Auto-detect and merge ALL duplicate Release records in the database.

Two releases are considered duplicates when they share the same
  lower(canonical_title) + chart_type + artist_id

The keeper is the record with the most MonthlyChartEntry rows (most chart
history). For conflicting entries (same chart + platform on both keeper and
duplicate) the keeper's data is preserved — points are NOT summed, because
these duplicates were the same song tracked twice, not the same song split
across platforms.

Usage:
    python manage.py auto_merge_duplicate_releases --dry-run
    python manage.py auto_merge_duplicate_releases
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Lower
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
from charts.management.commands.merge_duplicate_releases import (
    _merge_platform_chart_entries,
    _merge_artist_credits,
    _merge_metadata,
    _archive_duplicate,
    _log_merge,
)


def _safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def _merge_chart_entries_no_sum(dup, keeper, dry_run):
    """
    Reassign chart entries from dup to keeper.
    Where keeper already has an entry for the same chart+platform, the
    duplicate entry is simply deleted (keeper's score is kept as-is).
    """
    reassigned = 0
    dropped = 0

    dup_entries = list(MonthlyChartEntry.objects.filter(release=dup))
    for dup_entry in dup_entries:
        keeper_entry = MonthlyChartEntry.objects.filter(
            chart_id=dup_entry.chart_id,
            platform_id=dup_entry.platform_id,
            release=keeper,
        ).first()

        if keeper_entry:
            dropped += 1
            if not dry_run:
                dup_entry.delete()
        else:
            reassigned += 1
            if not dry_run:
                dup_entry.release = keeper
                dup_entry.save(update_fields=["release"])

    return reassigned, dropped


class Command(BaseCommand):
    help = "Find and merge all duplicate Release records (same title + artist + chart type)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
        parser.add_argument(
            "--chart-type", default=None, choices=["singles", "albums"],
            help="Limit to one chart type (default: both)"
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        chart_type_filter = options["chart_type"]
        prefix = "[DRY RUN] " if dry_run else ""

        # ── Find all duplicate groups ──────────────────────────────────────
        qs = Release.objects.exclude(status="archived")
        if chart_type_filter:
            qs = qs.filter(chart_type=chart_type_filter)

        # Group by (lower title, chart_type, artist_id) — any group with >1 = duplicates
        duplicate_groups = (
            qs
            .annotate(lower_title=Lower("canonical_title"))
            .values("lower_title", "chart_type", "artist_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .order_by("lower_title", "chart_type")
        )

        groups = list(duplicate_groups)
        if not groups:
            self.stdout.write(self.style.SUCCESS("No duplicate releases found."))
            return

        self.stdout.write(f"\n{prefix}Found {len(groups)} duplicate group(s):\n")

        total_merged = 0
        affected_keeper_ids = set()

        def _run_all():
            nonlocal total_merged

            for group in groups:
                lower_title = group["lower_title"]
                ct = group["chart_type"]
                artist_id = group["artist_id"]

                releases = list(
                    Release.objects.filter(
                        canonical_title__iexact=lower_title,
                        chart_type=ct,
                        artist_id=artist_id,
                    ).exclude(status="archived").order_by("id")
                )

                if len(releases) < 2:
                    continue

                # Keeper = most chart entries; tie-break = lowest id (oldest)
                entry_counts = {
                    r.id: MonthlyChartEntry.objects.filter(release=r).count()
                    for r in releases
                }
                keeper = max(releases, key=lambda r: (entry_counts[r.id], -r.id))
                duplicates = [r for r in releases if r.id != keeper.id]

                self.stdout.write(
                    f"{prefix}  [{ct}] {_safe(keeper.title)!r} "
                    f"by {_safe(keeper.artist.name)!r}  "
                    f"({len(duplicates)} duplicate(s))"
                )
                self.stdout.write(
                    f"{prefix}    Keeper  : id={keeper.id} entries={entry_counts[keeper.id]}"
                )
                for dup in duplicates:
                    self.stdout.write(
                        f"{prefix}    Merge   : id={dup.id} "
                        f"title={_safe(dup.title)!r} "
                        f"entries={entry_counts[dup.id]}"
                    )

                for dup in duplicates:
                    mce_r, mce_d = _merge_chart_entries_no_sum(dup, keeper, dry_run)
                    pce = _merge_platform_chart_entries(dup, keeper, dry_run)
                    rac = _merge_artist_credits(dup, keeper, dry_run)
                    meta = _merge_metadata(dup, keeper, dry_run)
                    Certification.objects.filter(release=dup).delete() if not dry_run else None
                    _archive_duplicate(dup, keeper, dry_run)

                    self.stdout.write(
                        f"{prefix}      id={dup.id}: "
                        f"mce_reassigned={mce_r} mce_dropped={mce_d} "
                        f"pce={pce} rac={rac}"
                    )
                    if not dry_run:
                        _log_merge(dup, keeper, {
                            "mce_reassigned": mce_r, "mce_dropped": mce_d,
                            "pce_reassigned": pce, "rac_moved": rac,
                            "meta_filled": meta,
                        })
                    total_merged += 1

                affected_keeper_ids.add(keeper.id)

        if dry_run:
            with transaction.atomic():
                _run_all()
                transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING(
                f"\nDry run -- {total_merged} duplicate(s) would be merged. Nothing saved."
            ))
        else:
            with transaction.atomic():
                _run_all()

            self.stdout.write("\nRecalculating certifications...")
            for rid in affected_keeper_ids:
                try:
                    recalculate_certifications(release=Release.objects.get(pk=rid))
                except Release.DoesNotExist:
                    pass

            try:
                AuditLog.objects.create(
                    action="auto_merge_duplicate_releases",
                    module="releases",
                    object_type="Release",
                    object_id="",
                    object_repr=f"Auto-merged {total_merged} duplicate releases",
                    old_value={},
                    new_value={
                        "groups": len(groups),
                        "duplicates_merged": total_merged,
                        "timestamp": timezone.now().isoformat(),
                    },
                    reason="Automated auto_merge_duplicate_releases command",
                    user=None, ip_address=None, user_agent="management-command",
                )
            except Exception:
                pass

            self.stdout.write(self.style.SUCCESS(
                f"\nDone. {total_merged} duplicate release(s) merged across "
                f"{len(affected_keeper_ids)} canonical record(s)."
            ))
