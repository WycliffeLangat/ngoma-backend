from django.db import migrations


def backfill_regional_charts(apps, schema_editor):
    # Use the canonical synchronizer so this deploy repairs regional charts
    # already created by 0014 from the truncated global Combined candidate
    # pool. The operation is idempotent and also rebuilds regional history.
    from charts.cms_utils import (
        harmonize_regional_chart_entries,
        sync_regional_chart_entries,
    )
    from charts.models import MonthlyChart

    charts = list(
        MonthlyChart.objects.all().order_by("chart_type", "year", "month", "id")
    )
    sync_regional_chart_entries(charts)
    harmonize_regional_chart_entries(charts)


class Migration(migrations.Migration):
    dependencies = [
        ("charts", "0014_regionalchartentry"),
    ]

    operations = [
        migrations.RunPython(backfill_regional_charts, migrations.RunPython.noop),
    ]
