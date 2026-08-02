"""
Find (and optionally fix) MonthlyChart records where `is_published` and
`status` disagree. The public API (see charts/app_data.py) only exposes a
chart when BOTH is_published=True and status='published' — the two fields
were historically settable independently (e.g. Django admin's list view only
exposes is_published), so they can drift apart and a chart can look
"published" in one place while staying invisible on the public site.

Usage:
    python manage.py fix_publish_status                       # report only
    python manage.py fix_publish_status --apply                # fix all mismatches
    python manage.py fix_publish_status --year 2026 --month 8 --apply
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from charts.models import MonthlyChart


class Command(BaseCommand):
    help = "Find/fix MonthlyChart records where is_published and status disagree."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None)
        parser.add_argument("--month", type=int, default=None)
        parser.add_argument(
            "--chart-type", default="",
            help="Restrict to one chart type (singles/albums). Default: both.",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="Apply the fix. Without this flag, only a report is printed.",
        )

    def handle(self, *args, **options):
        # Mismatch = exactly one of the two publish signals says "published"
        qs = MonthlyChart.objects.filter(
            Q(is_published=True, status__in=["draft", "pending_review", "approved", "rejected", "archived"]) |
            Q(is_published=False, status="published")
        )

        if options["year"] is not None:
            qs = qs.filter(year=options["year"])
        if options["month"] is not None:
            qs = qs.filter(month=options["month"])
        if options["chart_type"]:
            qs = qs.filter(chart_type=options["chart_type"])

        mismatches = list(qs.order_by("-year", "-month", "chart_type"))

        if not mismatches:
            self.stdout.write(self.style.SUCCESS("No is_published/status mismatches found."))
            return

        self.stdout.write(f"Found {len(mismatches)} mismatched MonthlyChart record(s):")
        for chart in mismatches:
            self.stdout.write(
                f"  - {chart.label} ({chart.chart_type}): "
                f"is_published={chart.is_published}, status={chart.status!r}"
            )

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("\nDry run only. Re-run with --apply to fix these."))
            return

        with transaction.atomic():
            for chart in mismatches:
                chart.is_published = True
                chart.status = "published"
                if not chart.published_at:
                    chart.published_at = timezone.now()
                chart.save(update_fields=["is_published", "status", "published_at", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"\nFixed {len(mismatches)} record(s) — both now published."))
