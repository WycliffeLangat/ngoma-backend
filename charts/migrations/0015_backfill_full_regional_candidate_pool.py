from django.db import migrations
from django.db.utils import DatabaseError


def backfill_regional_charts(apps, schema_editor):
    # Use the canonical synchronizer so this deploy repairs regional charts
    # already created by 0014 from the truncated global Combined candidate
    # pool. The operation is idempotent and also rebuilds regional history.
    #
    # This calls live app code (not the historical apps.get_model state),
    # which is fine for the real one-time deploy this was written for, but
    # means a full from-scratch migration replay (fresh test DB, new dev
    # clone) runs it against whatever the *current* models look like --
    # including columns added by migrations that come later than this one.
    # If the schema has moved on since, this backfill's job is redundant
    # anyway (every chart rebuild re-syncs regional entries and history), so
    # skip rather than fail the replay.
    from charts.cms_utils import (
        harmonize_regional_chart_entries,
        sync_regional_chart_entries,
    )
    from charts.models import MonthlyChart

    charts = list(
        MonthlyChart.objects.all().order_by("chart_type", "year", "month", "id")
    )
    if not charts:
        return
    try:
        sync_regional_chart_entries(charts)
        harmonize_regional_chart_entries(charts)
    except DatabaseError:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("charts", "0014_regionalchartentry"),
    ]

    operations = [
        migrations.RunPython(backfill_regional_charts, migrations.RunPython.noop),
    ]
