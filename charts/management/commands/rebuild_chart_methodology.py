"""Safely rebuild stored chart data under the canonical Top 100/Top 50 rules."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from charts.artist_credits import parse_artist_credit
from charts.cms_utils import harmonize_chart_history
from charts.methodology import (
    ALBUMS_PLATFORMS,
    SINGLES_PLATFORMS,
    WEEKLY_CHART_LIMIT,
    weekly_points,
)
from charts.models import Platform, PlatformChartEntry, Release, WeeklyUpload
from charts.pipeline import _sync_release_credits, rebuild_monthly_chart


class Command(BaseCommand):
    help = (
        "Recalculate weekly source points, monthly raw rankings, public Top 50 "
        "points, coverage, artist credits, history, and certifications."
    )

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Rebuild every stored period.")
        parser.add_argument("--year", type=int)
        parser.add_argument("--month", type=int)
        parser.add_argument("--chart-type", choices=["singles", "albums"])
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run the complete rebuild inside a rolled-back transaction.",
        )

    def handle(self, *args, **options):
        if not options["all"] and not (options["year"] and options["month"]):
            raise CommandError("Use --all or provide both --year and --month.")

        with transaction.atomic():
            summary = self._rebuild(options)
            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "DRY RUN" if options["dry_run"] else "APPLIED"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: {summary['weekly_updated']} weekly scores updated; "
            f"{summary['weekly_removed']} invalid weekly rows removed; "
            f"{summary['periods_rebuilt']} weekly-backed periods rebuilt; "
            f"{summary['release_credits_synced']} release credits synchronized."
        ))
        for chart_type, result in summary["harmonization"].items():
            self.stdout.write(
                f"  {chart_type}: {result['charts']} charts, "
                f"{result['rank_changes']} rank changes, "
                f"{result['scoring_changes']} public-score changes, "
                f"{result['history_changes']} history changes"
            )
        if options["dry_run"]:
            self.stdout.write("No database changes were committed.")

    def _scope(self, queryset, options):
        if options["chart_type"]:
            queryset = queryset.filter(chart_type=options["chart_type"])
        if not options["all"]:
            queryset = queryset.filter(
                year=options["year"],
                month=options["month"],
            )
        return queryset

    def _rebuild(self, options):
        core_names = set(SINGLES_PLATFORMS) | set(ALBUMS_PLATFORMS)
        Platform.objects.filter(name__in=core_names).update(
            chart_size=100,
            max_chart_size=50,
            points_base=101,
            active=True,
        )
        Platform.objects.filter(name__in=["Apple Music", "Audiomack"]).update(
            supports_singles=True,
            supports_albums=True,
        )
        Platform.objects.filter(
            name__in=["Boomplay", "Spotify", "YouTube", "Shazam"]
        ).update(supports_singles=True, supports_albums=False)

        uploads = self._scope(
            WeeklyUpload.objects.filter(processed=True),
            options,
        )
        entries = PlatformChartEntry.objects.filter(upload__in=uploads)
        invalid = entries.exclude(position__range=(1, WEEKLY_CHART_LIMIT))
        weekly_removed = invalid.count()
        invalid.delete()

        changed = []
        for entry in entries.filter(position__range=(1, WEEKLY_CHART_LIMIT)).iterator():
            expected = weekly_points(entry.position)
            if entry.points != expected:
                entry.points = expected
                changed.append(entry)
        if changed:
            PlatformChartEntry.objects.bulk_update(changed, ["points"], batch_size=1000)

        periods = list(
            uploads.filter(entries__isnull=False)
            .values_list("chart_type", "year", "month")
            .distinct()
            .order_by("chart_type", "year", "month")
        )
        for chart_type, year, month in periods:
            rebuild_monthly_chart(
                chart_type,
                year,
                month,
                harmonize=False,
            )

        credit_count = 0
        releases = Release.objects.all()
        if options["chart_type"]:
            releases = releases.filter(chart_type=options["chart_type"])
        for release in releases.select_related("artist").iterator():
            preserve_name = release.artist.artist_type in {"group", "band", "duo"}
            primary, parsed_featured = parse_artist_credit(
                release.artist.name,
                preserve_name=preserve_name,
            )
            explicit_featured, _ = parse_artist_credit(release.featured_artists)
            featured = [*parsed_featured, *explicit_featured]
            before = release.artist_credits.count()
            _sync_release_credits(
                release,
                primary or [release.artist.name],
                featured,
            )
            after = release.artist_credits.count()
            if after != before or len(primary) > 1 or featured:
                credit_count += 1

        affected_types = (
            [options["chart_type"]]
            if options["chart_type"]
            else ["singles", "albums"]
        )
        harmonization = {
            chart_type: harmonize_chart_history(chart_type=chart_type)
            for chart_type in affected_types
        }
        return {
            "weekly_updated": len(changed),
            "weekly_removed": weekly_removed,
            "periods_rebuilt": len(periods),
            "release_credits_synced": credit_count,
            "harmonization": harmonization,
        }
