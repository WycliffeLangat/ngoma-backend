from pathlib import Path

from django.conf import settings
from django.db import migrations

from charts.master_dataset import import_master_workbook


def reload_canonical_chart_data(apps, schema_editor):
    workbook = Path(settings.BASE_DIR) / "charts" / "seed_data" / "Ngoma_Charts_MASTER.xlsx"
    report = import_master_workbook(apps, workbook, clear=True)
    expected = 50 * 2 * len(report["months"])
    if report["combined_rows"] != expected:
        raise RuntimeError("Canonical chart reload did not import all Combined chart rows")


class Migration(migrations.Migration):
    dependencies = [("charts", "0005_reload_verified_metadata")]

    operations = [migrations.RunPython(reload_canonical_chart_data, migrations.RunPython.noop)]
