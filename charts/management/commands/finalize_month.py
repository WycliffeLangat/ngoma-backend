"""
Append a completed month from the DB into Ngoma_Charts_MASTER.xlsx and update
the MONTHS list in master_dataset.py so all downstream tools (seed_data,
export_frontend_data.py) automatically include the new month.

Usage:
    # Preview without writing anything
    python manage.py finalize_month --year 2026 --month 6 --dry-run

    # Apply
    python manage.py finalize_month --year 2026 --month 6
"""

import calendar
import re
from pathlib import Path

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from charts.artist_credits import release_credit_payload
from charts.models import MonthlyChart, MonthlyChartEntry, Platform


COMBINED_HEADERS = [
    "Month", "Rank", "Title", "Primary_Artist", "Featured_Artists",
    "Combined_Points_Raw", "Display_Points", "Platforms", "Platforms_Max",
    "Weeks", "Release_Year", "Confidence",
]

PLATFORM_HEADERS = ["Month", "Platform", "Rank", "Title", "Artist", "Points", "Weeks"]

PLATFORM_ORDER = {
    "singles": ["Apple Music", "Audiomack", "Boomplay", "Spotify", "YouTube", "Shazam"],
    "albums":  ["Apple Music", "Audiomack"],
}


class Command(BaseCommand):
    help = (
        "Append a completed month's chart data from the DB into "
        "Ngoma_Charts_MASTER.xlsx, then update MONTHS in master_dataset.py."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year",  type=int, required=True, help="e.g. 2026")
        parser.add_argument("--month", type=int, required=True, help="e.g. 6  (June)")
        parser.add_argument(
            "--workbook",
            default=str(
                Path(settings.BASE_DIR) / "charts" / "seed_data" / "Ngoma_Charts_MASTER.xlsx"
            ),
            help="Path to Ngoma_Charts_MASTER.xlsx (default: charts/seed_data/Ngoma_Charts_MASTER.xlsx)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be written without modifying any files.",
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        year      = options["year"]
        month     = options["month"]
        dry_run   = options["dry_run"]
        wb_path   = Path(options["workbook"])
        month_label = f"{calendar.month_name[month]} {year}"

        mode = "DRY RUN" if dry_run else "APPLY"
        self.stdout.write(f"\n[{mode}] Finalizing {month_label}\n")

        # 1. Validate both chart types are published and fully populated
        self._validate_month(year, month, month_label)

        # 2. Check the month is not already in the workbook
        wb = openpyxl.load_workbook(wb_path)
        self._check_not_duplicate(wb, month_label)

        # 3. Build and (optionally) append rows
        total_combined = 0
        total_platform = 0

        for chart_type in ("singles", "albums"):
            n_combined, n_platform = self._append_chart_type(
                wb, chart_type, year, month, month_label, dry_run
            )
            total_combined += n_combined
            total_platform += n_platform

        # 4. Save workbook + update source files
        if not dry_run:
            wb.save(wb_path)
            self.stdout.write(self.style.SUCCESS(f"\nSaved {wb_path.name}"))
            self._update_months_constant(month_label)
            self._update_validate_check()
            self._print_next_steps(wb_path)
        else:
            self.stdout.write(
                f"\n  Would append {total_combined} combined rows "
                f"and {total_platform} platform rows."
            )
            self.stdout.write(self.style.WARNING("\nDry run complete — no files modified."))

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_month(self, year, month, month_label):
        for chart_type in ("singles", "albums"):
            try:
                chart = MonthlyChart.objects.get(
                    year=year, month=month, chart_type=chart_type,
                    is_published=True, status="published",
                )
            except MonthlyChart.DoesNotExist:
                raise CommandError(
                    f"The {chart_type} chart for {month_label} is not published. "
                    "Publish it in the CMS before finalizing."
                )
            count = MonthlyChartEntry.objects.filter(
                chart=chart, platform__isnull=True, rank__lte=50
            ).count()
            if count < 50:
                raise CommandError(
                    f"The {chart_type} combined chart for {month_label} has only "
                    f"{count} entries (need 50). Make sure all weekly uploads for "
                    "the month are processed."
                )

    def _check_not_duplicate(self, wb, month_label):
        ws = wb["Singles_Combined"]
        for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
            if row[0] and str(row[0]).strip() == month_label:
                raise CommandError(
                    f"{month_label} is already in the master workbook. Nothing to do."
                )

    # ------------------------------------------------------------------
    # Row building and appending
    # ------------------------------------------------------------------

    def _append_chart_type(self, wb, chart_type, year, month, month_label, dry_run):
        chart = MonthlyChart.objects.get(year=year, month=month, chart_type=chart_type)
        platform_order = PLATFORM_ORDER[chart_type]
        platform_max   = len(platform_order)
        label          = chart_type.capitalize()

        # ---- Combined ----
        combined_entries = (
            MonthlyChartEntry.objects
            .filter(chart=chart, platform__isnull=True, rank__lte=50)
            .select_related("release", "release__artist")
            .prefetch_related("release__artist_credits__artist")
            .order_by("rank")
        )

        combined_rows = []
        for entry in combined_entries:
            release = entry.release
            credits = release_credit_payload(release, entry_featured=entry.featured_artists or "")
            combined_rows.append([
                month_label,
                entry.rank,
                release.title,
                credits["primary_artist_credit"] or release.artist.display_name or release.artist.name,
                credits["featured_artist_credit"] or "",
                entry.raw_total_points if entry.raw_total_points is not None else entry.total_points,
                51 - entry.rank,           # Display_Points: rank 1 = 50, rank 50 = 1
                entry.platform_count or 0,
                platform_max,
                entry.weeks_on_chart or 1,
                entry.release_year or (release.release_year if hasattr(release, "release_year") else None),
                entry.confidence or "web-verified",
            ])

        self.stdout.write(f"  {label}_Combined : {len(combined_rows)} rows")
        if not dry_run:
            ws_combined = wb[f"{label}_Combined"]
            for row in combined_rows:
                ws_combined.append(row)

        # ---- Platforms ----
        platforms = {
            p.name: p
            for p in Platform.objects.filter(name__in=platform_order)
        }

        platform_rows = []
        for plat_name in platform_order:
            if plat_name not in platforms:
                continue
            plat = platforms[plat_name]
            plat_entries = (
                MonthlyChartEntry.objects
                .filter(chart=chart, platform=plat)
                .select_related("release", "release__artist")
                .prefetch_related("release__artist_credits__artist")
                .order_by("rank")
            )
            for entry in plat_entries:
                release = entry.release
                credits = release_credit_payload(release, entry_featured=entry.featured_artists or "")
                platform_rows.append([
                    month_label,
                    plat_name,
                    entry.rank,
                    release.title,
                    credits["artist_credit"],
                    entry.raw_total_points if entry.raw_total_points is not None else entry.total_points,
                    entry.weeks_on_chart or 1,
                ])

        self.stdout.write(f"  {label}_Platforms: {len(platform_rows)} rows")
        if not dry_run:
            ws_platform = wb[f"{label}_Platforms"]
            for row in platform_rows:
                ws_platform.append(row)

        return len(combined_rows), len(platform_rows)

    # ------------------------------------------------------------------
    # Source file updates
    # ------------------------------------------------------------------

    def _update_months_constant(self, month_label):
        """Append month_label to the MONTHS list in master_dataset.py."""
        import charts.master_dataset as _md
        dataset_path = Path(_md.__file__)
        text = dataset_path.read_text(encoding="utf-8")

        match = re.search(r"(MONTHS\s*=\s*\[.*?\])", text, re.DOTALL)
        if not match:
            self.stdout.write(self.style.WARNING(
                f"Could not auto-update MONTHS. Add '{month_label}' to "
                "charts/master_dataset.py manually."
            ))
            return

        old_block = match.group(1)
        # Remove the closing bracket and any existing trailing comma before appending.
        new_block = old_block.rstrip()[:-1].rstrip().rstrip(",") + f',\n    "{month_label}",\n]'
        dataset_path.write_text(text.replace(old_block, new_block), encoding="utf-8")
        self.stdout.write(f"Updated MONTHS in master_dataset.py: added '{month_label}'")

    def _update_validate_check(self):
        """
        Replace the hardcoded 900-row check in validate_master_data() with a
        dynamic check so it scales as months are added.
        """
        import charts.master_dataset as _md
        dataset_path = Path(_md.__file__)
        text = dataset_path.read_text(encoding="utf-8")

        old_check = 'if combined_total != 900:'
        new_check = 'if combined_total != 50 * 2 * len(MONTHS):'
        old_error = '"The two Combined sheets must contain exactly 900 rows"'
        new_error  = 'f"The two Combined sheets must contain exactly {50 * 2 * len(MONTHS)} rows"'

        updated = (
            text
            .replace(old_check, new_check)
            .replace(old_error, new_error)
        )
        if updated != text:
            dataset_path.write_text(updated, encoding="utf-8")
            self.stdout.write("Updated validate_master_data() row count to scale with MONTHS")

    def _print_next_steps(self, wb_path):
        self.stdout.write(
            "\nNext step — regenerate chartData.js:\n"
            "  python scripts/export_frontend_data.py \\\n"
            f"    {wb_path} \\\n"
            "    ../../ngoma_charts_frontend/ngoma_deploy/src/data/chartData.js"
        )
