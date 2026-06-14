from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from charts.master_dataset import import_master_workbook


class Command(BaseCommand):
    help = "Replace chart data with the documented Ngoma Charts master workbook"

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

    @transaction.atomic
    def handle(self, *args, **options):
        report = import_master_workbook(
            apps,
            options["workbook"],
            clear=options["clear"],
            write_line=self.stdout.write,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {report['combined_rows']} Combined rows, "
                f"{report['platform_rows']} platform rows, current month May 2026"
            )
        )
