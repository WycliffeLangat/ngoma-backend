import io
from unittest.mock import patch

import openpyxl
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import (
    Artist,
    ChartUpload,
    ChartType,
    MonthlyChartEntry,
    Platform,
    PlatformChartEntry,
    Release,
    WeeklyUpload,
)
from .pipeline import get_or_create_release, process_weekly_upload


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


def single_column_workbook_bytes(value):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(['Apple Music'])
    sheet.append([value])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def final_chart_workbook_bytes(title='Song A', artist='Artist A'):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(['rank', 'title', 'artist', 'total_points'])
    sheet.append([1, title, artist, 50])
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

    def test_reprocessing_corrected_upload_prunes_swapped_release(self):
        Artist.objects.create(name='Known Artist', slug='known-artist')
        upload = WeeklyUpload.objects.create(
            chart_type=ChartType.SINGLES,
            year=2026,
            month=7,
            week=2,
            file='July 2026 Week 2 Singles.xlsx',
        )

        process_weekly_upload(
            upload,
            io.BytesIO(single_column_workbook_bytes(
                'Known Artist - Real Song'
            )),
        )
        swapped = Release.objects.get(
            title='Known Artist',
            artist__name='Real Song',
        )

        result = process_weekly_upload(
            upload,
            io.BytesIO(single_column_workbook_bytes(
                'Real Song - Known Artist'
            )),
        )

        self.assertEqual(result['orphaned_releases_pruned'], 1)
        self.assertFalse(Release.objects.filter(pk=swapped.pk).exists())
        self.assertTrue(Release.objects.filter(
            title='Real Song',
            artist__name='Known Artist',
        ).exists())

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

        self.assertEqual(response.status_code, 400)

    def test_weekly_workbook_can_be_viewed_downloaded_edited_and_reprocessed(self):
        response = self.client.post(
            reverse('cms-weekly-uploads-list'),
            {
                'chart_type': ChartType.SINGLES,
                'year': 2026,
                'month': 7,
                'week': 3,
                'file': SimpleUploadedFile(
                    'July 2026 Week 3 Singles.xlsx',
                    single_column_workbook_bytes('Original Song - Artist A'),
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                ),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 201, response.data)
        upload_id = response.data['id']
        self.assertTrue(response.data['workbook_available'])

        workbook_response = self.client.get(
            reverse('cms-weekly-uploads-workbook', args=[upload_id]),
        )
        self.assertEqual(workbook_response.status_code, 200, workbook_response.data)
        self.assertEqual(workbook_response.data['sheets'][0]['rows'][1][0], 'Original Song - Artist A')

        download_response = self.client.get(
            reverse('cms-weekly-uploads-download', args=[upload_id]),
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn('spreadsheetml.sheet', download_response['Content-Type'])

        sheets = workbook_response.data['sheets']
        sheets[0]['rows'][1][0] = 'Corrected Song - Artist A'
        edit_response = self.client.patch(
            reverse('cms-weekly-uploads-workbook', args=[upload_id]),
            {'sheets': sheets, 'filename': 'July 2026 Week 3 Singles.xlsx'},
            format='json',
        )
        self.assertEqual(edit_response.status_code, 200, edit_response.data)
        upload = WeeklyUpload.objects.get(pk=upload_id)
        self.assertTrue(upload.processed)
        self.assertEqual(upload.entries_processed, 1)
        self.assertTrue(Release.objects.filter(title='Corrected Song', artist__name='Artist A').exists())
        self.assertFalse(Release.objects.filter(title='Original Song', artist__name='Artist A').exists())


class CmsChartUploadWorkbookTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='chart-upload-admin',
            email='chart-upload@example.com',
            password='test-password',
        )
        self.client.force_authenticate(self.user)

    def test_chart_upload_workbook_can_be_viewed_downloaded_and_saved_to_rows(self):
        response = self.client.post(
            reverse('cms-chart-uploads-list'),
            {
                'chart_type': ChartType.SINGLES,
                'year': 2026,
                'month': 7,
                'file': SimpleUploadedFile(
                    'July 2026 Singles.xlsx',
                    final_chart_workbook_bytes(),
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                ),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 201, response.data)
        upload_id = response.data['id']
        self.assertTrue(response.data['workbook_available'])
        self.assertEqual(response.data['rows_data'][0]['title'], 'Song A')

        workbook_response = self.client.get(
            reverse('cms-chart-uploads-workbook', args=[upload_id]),
        )
        self.assertEqual(workbook_response.status_code, 200, workbook_response.data)
        sheets = workbook_response.data['sheets']
        sheets[0]['rows'][1][1] = 'Edited Song'

        edit_response = self.client.patch(
            reverse('cms-chart-uploads-workbook', args=[upload_id]),
            {'sheets': sheets, 'filename': 'July 2026 Singles.xlsx'},
            format='json',
        )
        self.assertEqual(edit_response.status_code, 200, edit_response.data)
        upload = ChartUpload.objects.get(pk=upload_id)
        self.assertEqual(upload.rows_data[0]['title'], 'Edited Song')
        self.assertEqual(upload.validation_summary['error_count'], 0)

        download_response = self.client.get(
            reverse('cms-chart-uploads-download', args=[upload_id]),
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn('spreadsheetml.sheet', download_response['Content-Type'])

