"""
Completely remove all chart data tied to a specific year/month period —
weekly uploads, platform chart entries, the monthly chart period(s), and any
release/artist that only ever existed because of that data — so the period
can be re-uploaded from scratch.

Usage:
    python manage.py purge_period --year 2026 --month 7 --dry-run
    python manage.py purge_period --year 2026 --month 7 --apply
    python manage.py purge_period --year 2026 --month 7 --apply --chart-type singles
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from charts.models import (
    Artist, ChartType, MonthlyChart, MonthlyChartEntry, PlatformChartEntry,
    Release, WeeklyUpload,
)
from charts.cms_utils import harmonize_chart_history, prune_orphaned_releases, recalculate_certifications


class Command(BaseCommand):
    help = (
        "Completely remove all chart data for a given year/month — weekly "
        "uploads, platform/monthly chart entries, the chart period(s), and "
        "any release/artist left with zero remaining chart data anywhere."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument(
            "--chart-type", default="",
            help="Restrict to one chart type (singles/albums). Default: both.",
        )
        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument("--dry-run", action="store_true", help="Preview without modifying the database")
        group.add_argument("--apply", action="store_true", help="Apply the purge (default)")

    def handle(self, *args, **options):
        year, month = options["year"], options["month"]
        dry_run = options["dry_run"]
        chart_types = [options["chart_type"]] if options["chart_type"] else [ChartType.SINGLES, ChartType.ALBUMS]
        mode_label = "DRY RUN" if dry_run else "APPLY"

        self.stdout.write(self.style.WARNING(
            f"\n[{mode_label}] Purging ALL chart data for {year}-{month:02d}, chart_types={chart_types}\n"
        ))

        upload_ids = list(
            WeeklyUpload.objects.filter(year=year, month=month, chart_type__in=chart_types)
            .values_list("id", flat=True)
        )
        chart_ids = list(
            MonthlyChart.objects.filter(year=year, month=month, chart_type__in=chart_types)
            .values_list("id", flat=True)
        )

        release_ids = set(
            PlatformChartEntry.objects.filter(upload_id__in=upload_ids).values_list("release_id", flat=True)
        ) | set(
            MonthlyChartEntry.objects.filter(chart_id__in=chart_ids).values_list("release_id", flat=True)
        )
        artist_ids = set(
            Release.objects.filter(id__in=release_ids).values_list("artist_id", flat=True)
        )

        pce_count = PlatformChartEntry.objects.filter(upload_id__in=upload_ids).count()
        mce_count = MonthlyChartEntry.objects.filter(chart_id__in=chart_ids).count()

        self.stdout.write(f"  WeeklyUploads to delete   : {len(upload_ids)}")
        self.stdout.write(f"  PlatformChartEntries      : {pce_count}")
        self.stdout.write(f"  MonthlyChart periods      : {len(chart_ids)}")
        self.stdout.write(f"  MonthlyChartEntries       : {mce_count}")
        self.stdout.write(f"  Releases touched          : {len(release_ids)}")
        self.stdout.write(f"  Artists touched           : {len(artist_ids)}\n")

        if dry_run:
            would_orphan_releases = [
                rid for rid in release_ids
                if not PlatformChartEntry.objects.filter(release_id=rid).exclude(upload_id__in=upload_ids).exists()
                and not MonthlyChartEntry.objects.filter(release_id=rid).exclude(chart_id__in=chart_ids).exists()
            ]
            would_orphan_artists = [
                aid for aid in artist_ids
                if not Release.objects.filter(artist_id=aid).exclude(id__in=would_orphan_releases).exists()
            ]
            self.stdout.write(f"  Would prune {len(would_orphan_releases)} release(s) left with zero remaining chart data")
            self.stdout.write(f"  Would prune {len(would_orphan_artists)} artist(s) left with zero remaining releases")
            self.stdout.write(self.style.WARNING("\nDry run only — nothing was deleted. Re-run with --apply to execute.\n"))
            return

        with transaction.atomic():
            WeeklyUpload.objects.filter(id__in=upload_ids).delete()
            MonthlyChart.objects.filter(id__in=chart_ids).delete()

        pruned_releases = prune_orphaned_releases(release_ids)

        pruned_artists = 0
        for aid in artist_ids:
            if not Release.objects.filter(artist_id=aid).exists():
                Artist.objects.filter(pk=aid).delete()
                pruned_artists += 1

        for ct in chart_types:
            harmonize_chart_history(chart_type=ct)
        recalculate_certifications()

        self.stdout.write(self.style.SUCCESS(
            f"\nDeleted {len(upload_ids)} upload(s), {len(chart_ids)} chart period(s). "
            f"Pruned {pruned_releases} release(s), {pruned_artists} artist(s).\n"
        ))
