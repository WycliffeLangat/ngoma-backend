from pathlib import Path

from django.conf import settings
from django.db import migrations

from charts.master_dataset import import_master_workbook


def load_master_dataset(apps, schema_editor):
    workbook = Path(settings.BASE_DIR) / "charts" / "seed_data" / "Ngoma_Charts_MASTER.xlsx"
    report = import_master_workbook(apps, workbook, clear=True)
    expected = 50 * 2 * len(report["months"])
    if report["combined_rows"] != expected:
        raise RuntimeError(f"Master dataset migration did not import exactly {expected} Combined rows")


class Migration(migrations.Migration):
    dependencies = [("charts", "0003_master_dataset_fields")]

    operations = [migrations.RunPython(load_master_dataset, migrations.RunPython.noop)]
