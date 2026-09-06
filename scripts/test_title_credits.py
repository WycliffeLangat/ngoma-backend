import os
import sys
from pathlib import Path

backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend))
os.environ['DJANGO_SETTINGS_MODULE'] = 'ngoma_backend.settings'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import django
django.setup()
from django.conf import settings
from django.test.utils import get_runner
# The normal migration path imports historical workbooks. Unit tests need
# the current schema, without that unrelated historical seed data.
settings.MIGRATION_MODULES = {'charts': None}
settings.CHART_JOBS_ASYNC = False
sys.exit(bool(get_runner(settings)(verbosity=1, interactive=False).run_tests([
    'charts.test_title_credits', 'charts.tests.PublicAppDataSyncTests',
])))
