"""
Merge all duplicate Release records that share the same canonical title and
chart type into a single canonical record.

The keeper is the record with the most MonthlyChartEntry rows (most data).
All other matching records are merged into it using the same logic as
merge_duplicate_releases, then archived.

Usage (dry-run):
    python manage.py merge_releases_by_title --title "Backbencher" --chart-type singles --dry-run

Apply:
    python manage.py merge_releases_by_title --title "Backbencher" --chart-type singles
"""

from django.core.management.base import BaseCommand, CommandError
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
from charts.management.commands.merge_duplicate_releases import (
    _merge_chart_entries,
    _merge_platform_chart_entries,
    _merge_artist_credits,
    _merge_metadata,
    _merge_certifications,
    _archive_duplicate,
    _log_merge,
)


class Command(BaseCommand):
    help = "Merge all duplicate Release records sharing a canonical title into one."

    def add_arguments(self, parser):
        parser.add_argument("--title", required=True, help="Release title to deduplicate (case-insensitive)")
        parser.add_argument("--chart-type", default="singles", choices=["singles", "albums"], help="Chart type (default: singles)")
        parser.add_argument("--dry-run", action="store_true", help="Preview without writing")

    def handle(self, *args, **options):
        canonical = options["title"].strip().lower()
        chart_type = options["chart_type"]
        dry_run = options["dry_run"]
        prefix = "[DRY RUN] " if dry_run else ""

        releases = list(
            Release.objects.filter(
                canonical_title=canonical,
                chart_type=chart_type,
            ).exclude(status="archived").order_by("id")
        )

        if not releases:
            self.stdout.write(self.style.WARNING(
                f"No active releases found with canonical_title={repr(canonical)}, chart_type={repr(chart_type)}"
            ))
            return

        self.stdout.write(f"\n{prefix}Found {len(releases)} release(s) for {repr(canonical)} / {chart_type}:")
        entry_counts = {}
        for r in releases:
            count = MonthlyChartEntry.objects.filter(release=r).count()
            entry_counts[r.id] = count
            self.stdout.write(f"  id={r.id}  artist={repr(r.artist.name)}  title={repr(r.title)}  entries={count}")

        if len(releases) == 1:
            self.stdout.write(self.style.SUCCESS("Only one record — nothing to merge."))
            return

        # Keeper = record with the most chart entries (ties broken by lowest ID = oldest)
        keeper = max(releases, key=lambda r: (entry_counts[r.id], -r.id))
        duplicates = [r for r in releases if r.id != keeper.id]

        self.stdout.write(f"\n{prefix}Keeper: id={keeper.id}  {repr(keeper.title)}  by {repr(keeper.artist.name)}")
        for dup in duplicates:
            self.stdout.write(f"{prefix}Merge:  id={dup.id}  {repr(dup.title)}  by {repr(dup.artist.name)}")

        def _run():
            for dup in duplicates:
                mce_r, mce_m = _merge_chart_entries(dup, keeper, dry_run)
                pce = _merge_platform_chart_entries(dup, keeper, dry_run)
                rac = _merge_artist_credits(dup, keeper, dry_run)
                meta = _merge_metadata(dup, keeper, dry_run)
                certs = _merge_certifications(dup, keeper, dry_run)
                _archive_duplicate(dup, keeper, dry_run)
                self.stdout.write(
                    f"{prefix}  id={dup.id} -> id={keeper.id}: "
                    f"mce_reassigned={mce_r} mce_merged={mce_m} "
                    f"pce={pce} rac={rac} meta={meta} certs_deleted={certs}"
                )
                if not dry_run:
                    _log_merge(dup, keeper, {
                        "mce_reassigned": mce_r, "mce_merged": mce_m,
                        "pce_reassigned": pce, "rac_moved": rac,
                        "meta_filled": meta, "certs_deleted": certs,
                    })

        if dry_run:
            _run()
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("\nDry run — nothing saved."))
        else:
            with transaction.atomic():
                _run()
            self.stdout.write("\nRecalculating certifications...")
            recalculate_certifications(release=keeper)
            try:
                AuditLog.objects.create(
                    action="merge_release",
                    module="releases",
                    object_type="Release",
                    object_id=str(keeper.pk),
                    object_repr=str(keeper)[:255],
                    old_value={"merged_ids": [d.pk for d in duplicates]},
                    new_value={"title": canonical, "chart_type": chart_type},
                    reason=f"merge_releases_by_title: {repr(canonical)}",
                    user=None, ip_address=None, user_agent="management-command",
                )
            except Exception:
                pass
            self.stdout.write(self.style.SUCCESS(
                f"\nDone. {len(duplicates)} duplicate(s) merged into id={keeper.id}."
            ))
