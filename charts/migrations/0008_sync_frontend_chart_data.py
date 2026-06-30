from pathlib import Path

from django.conf import settings
from django.db import migrations, models

from charts.master_dataset import import_master_workbook


def sync_frontend_chart_data(apps, schema_editor):
    workbook = Path(settings.BASE_DIR) / "charts" / "seed_data" / "Ngoma_Charts_MASTER.xlsx"
    report = import_master_workbook(apps, workbook, clear=True)
    expected = 50 * 2 * len(report["months"])
    if report["combined_rows"] != expected:
        raise RuntimeError("Frontend chart sync did not import all Combined chart rows")


class Migration(migrations.Migration):
    dependencies = [
        ("charts", "0003_country_dataqualityissue_placeholdermodule_and_more"),
        ("charts", "0007_reload_top_50_movements"),
    ]

    operations = [
        migrations.AlterField(
            model_name="monthlychart",
            name="label",
            field=models.CharField(max_length=50, help_text="e.g. 'September 2025'"),
        ),
        migrations.RunPython(sync_frontend_chart_data, migrations.RunPython.noop),
    ]
