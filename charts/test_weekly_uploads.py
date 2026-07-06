import io
from unittest.mock import patch

import openpyxl
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import (
    ChartType,
    MonthlyChartEntry,
    Platform,
    PlatformChartEntry,
    WeeklyUpload,
)
from .pipeline import get_or_create_release


PLATFORMS = [
    'Apple Music',
    'Audiomack',
    'Boomplay',
    'Spotify',
    'YouTube',
    'Shazam',
]


def weekly_workbook_bytes():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(PLATFORMS)
    sheet.append(['Song A - Artist A'] * len(PLATFORMS))
    sheet.append(['Song B - Artist B'] * len(PLATFORMS))
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class CmsWeeklyUploadTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='weekly-admin',
            email='weekly@example.com',
            password='test-password',
        )
        self.client.force_authenticate(self.user)
        for order, name in enumerate(PLATFORMS):
            Platform.objects.update_or_create(
                slug=name.lower().replace(' ', '-'),
                defaults={
                    'name': name,
                    'short_name': name,
                    'points_base': 101,
                    'max_chart_size': 100,
                    'supports_singles': True,
                    'active': True,
                    'display_order': order,
                },
            )

    def test_raw_xlsx_is_processed_without_persisting_to_image_storage(self):
        chart_file = SimpleUploadedFile(
            'July 2026 Week 1 Singles.xlsx',
            weekly_workbook_bytes(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        with patch(
            'charts.pipeline.get_or_create_release',
            wraps=get_or_create_release,
        ) as release_resolver:
            response = self.client.post(
                reverse('cms-weekly-uploads-list'),
                {
                    'chart_type': ChartType.SINGLES,
                    'year': 2026,
                    'month': 7,
                    'week': 1,
                    'file': chart_file,
                },
                format='multipart',
            )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(release_resolver.call_count, 2)
        upload = WeeklyUpload.objects.get(year=2026, month=7, week=1)
        self.assertTrue(upload.processed)
        self.assertEqual(upload.entries_processed, 12)
        self.assertEqual(upload.file.name, 'July 2026 Week 1 Singles.xlsx')
        self.assertEqual(response.data['original_filename'], 'July 2026 Week 1 Singles.xlsx')
        self.assertNotIn('file', response.data)
        self.assertEqual(PlatformChartEntry.objects.filter(upload=upload).count(), 12)
        self.assertEqual(
            MonthlyChartEntry.objects.filter(
                chart__year=2026,
                chart__month=7,
                chart__chart_type=ChartType.SINGLES,
                platform__isnull=True,
            ).count(),
            2,
        )
        self.assertFalse(
            MonthlyChartEntry.objects.filter(
                chart__year=2026,
                chart__month=7,
                platform__isnull=True,
            ).exclude(weeks_on_chart=1).exists()
        )

    def test_weekly_upload_rejects_non_excel_file(self):
        response = self.client.post(
            reverse('cms-weekly-uploads-list'),
            {
                'chart_type': ChartType.SINGLES,
                'year': 2026,
                'month': 7,
                'week': 1,
                'file': SimpleUploadedFile(
                    'week-1.csv',
                    b'Apple Music\nSong - Artist',
                    content_type='text/csv',
                ),
            },
            format='multipart',
        )

