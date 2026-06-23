from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from charts.master_dataset import import_master_workbook

DEFAULT_MERGE_WORKBOOK = Path(settings.BASE_DIR) / "Data" / "ngoma_duplicate_releases_final_merge_ready.xlsx"


class Command(BaseCommand):
    help = (
        "Seed chart data from the master workbook. "
        "Automatically applies the duplicate-release merge workbook when present."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workbook",
            default=str(Path(settings.BASE_DIR) / "charts" / "seed_data" / "Ngoma_Charts_MASTER.xlsx"),
            help="Path to Ngoma_Charts_MASTER.xlsx",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing chart records before importing",
        )
        parser.add_argument(
            "--merge-workbook",
            default=str(DEFAULT_MERGE_WORKBOOK),
            help=(
                "Path to the duplicate-release merge workbook "
                f"(default: Data/ngoma_duplicate_releases_final_merge_ready.xlsx). "
                "Auto-applied when the file exists."
            ),
        )
        parser.add_argument(
            "--no-merge",
            action="store_true",
            help="Skip merge-workbook canonicalization and import raw master data only.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        merge_path = None if options["no_merge"] else options["merge_workbook"]
        report = import_master_workbook(
            apps,
            options["workbook"],
            clear=options["clear"],
            write_line=self.stdout.write,
            merge_workbook_path=merge_path,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {report['combined_rows']} Combined rows, "
                f"{report['platform_rows']} platform rows, current month May 2026"
            )
        )
