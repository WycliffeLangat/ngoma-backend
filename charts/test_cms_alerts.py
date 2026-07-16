from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    AdminNotification,
    Artist,
    BackupRecord,
    Certification,
    CertificationRule,
    ChartUpload,
    Country,
    DataQualityIssue,
    InternalNote,
    MediaAsset,
    MethodologySetting,
    MonthlyChart,
    NewsArticle,
    PageContent,
    Platform,
    Release,
)


class CmsDashboardAlertTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create_superuser('alert-admin', 'alerts@example.com', 'password')
        self.client.force_authenticate(self.admin)
        # Chart data is loaded by historical migrations; alert tests need a clean,
        # explicit baseline so seeded production-like gaps do not affect assertions.
        for model in [
            AdminNotification,
            DataQualityIssue,
            InternalNote,
            BackupRecord,
            MediaAsset,
            PageContent,
            NewsArticle,
            ChartUpload,
            MonthlyChart,
            Certification,
            Release,
            Artist,
            Platform,
            Country,
            MethodologySetting,
            CertificationRule,
        ]:
            model.objects.all().delete()
        Country.objects.create(name='Kenya', code='KE', region='East Africa', active=True)
        MethodologySetting.objects.create(version='v1', name='Current', is_active=True)
        for level, threshold in [('gold', 5000), ('platinum', 10000), ('diamond', 20000)]:
            CertificationRule.objects.update_or_create(level=level, defaults={'threshold': threshold, 'active': True})
        BackupRecord.objects.create(status='created', created_by=self.admin)

    def dashboard(self):
        cards_response = self.client.get('/api/v1/cms/dashboard/')
        self.assertEqual(cards_response.status_code, 200, cards_response.content)
        insights_response = self.client.get('/api/v1/cms/dashboard/insights/')
        self.assertEqual(insights_response.status_code, 200, insights_response.content)
        data = insights_response.json()
        data['cards'] = {**cards_response.json()['cards'], **data['cards']}
        return data

    def test_dashboard_alerts_include_actionable_details_and_live_summary(self):
        Artist.objects.create(name='Countryless Artist', slug='countryless-artist')
        Artist.objects.create(name='Partial Artist', slug='partial-artist', country='Kenya')
        Artist.objects.create(name='Archived Artist', slug='archived-artist', status='archived')
        MonthlyChart.objects.create(
            year=2026,
            month=5,
            chart_type='singles',
            label='ignored',
            status='draft',
            is_published=True,
        )
        NewsArticle.objects.create(
            title='Incomplete live story',
            slug='incomplete-live-story',
            category='chart_news',
            status='draft',
            is_published=True,
        )
        DataQualityIssue.objects.create(
            module='charts',
            issue_type='manual_check',
            severity='error',
            description='Verify the imported points total.',
        )
        AdminNotification.objects.create(
            title='Editorial reminder',
            message='Confirm the source attribution.',
            level='warning',
            user=self.admin,
        )

        data = self.dashboard()
        alerts = {alert['id']: alert for alert in data['alerts']}

        self.assertIn('artists-missing-country', alerts)
        self.assertEqual(alerts['artists-missing-country']['count'], 1)
        self.assertEqual(alerts['artists-missing-country']['details'][0]['label'], 'Countryless Artist')
        self.assertIn('artists-partial-country', alerts)
        self.assertIn('chart-publication-state-mismatch', alerts)
        self.assertIn('charts-without-entries', alerts)
        self.assertIn('news-publication-state-mismatch', alerts)
        self.assertIn('open-data-quality-reports', alerts)
        self.assertIn('admin-notifications-unread', alerts)

        for alert in data['alerts']:
            self.assertEqual(
                set(alert),
                {'id', 'level', 'category', 'title', 'message', 'count', 'module', 'target_url', 'action', 'details'},
            )
            self.assertTrue(alert['action'])
            self.assertTrue(alert['target_url'])

        self.assertEqual(data['alerts'][0]['level'], 'error')
        self.assertGreaterEqual(data['alert_summary']['error'], 1)
        self.assertEqual(data['alert_summary']['total'], len(data['alerts']))
        self.assertEqual(data['cards']['system_health'], 'ACTION_REQUIRED')

    def test_automatic_visible_certifications_do_not_need_official_alerts(self):
        artist = Artist.objects.create(name='Certified Artist', slug='certified-artist')
        release = Release.objects.create(
            title='Certified Song',
            artist=artist,
            chart_type='singles',
            canonical_title='certified song',
        )
        Certification.objects.create(
            release=release,
            level='gold',
            total_points=5000,
            is_official=False,
            is_hidden=False,
        )

        data = self.dashboard()
        alert_ids = {alert['id'] for alert in data['alerts']}

        self.assertNotIn('certifications-unofficial-visible', alert_ids)
        self.assertEqual(data['cards']['automatic_certifications'], 1)

    def test_upload_validation_findings_are_split_by_severity(self):
        ChartUpload.objects.create(
            chart_type='singles',
            year=2026,
            month=6,
            original_filename='june.csv',
            status='pending_review',
            row_count=2,
            validation_summary={
                'error_count': 1,
                'warning_count': 2,
                'errors': [{'row': 2, 'message': 'Missing artist'}],
                'warnings': [{'row': 1, 'message': 'Missing year'}],
            },
        )

        alerts = {alert['id']: alert for alert in self.dashboard()['alerts']}

        self.assertEqual(alerts['upload-validation-errors']['count'], 1)
        self.assertEqual(alerts['upload-validation-errors']['details'][0]['label'], 'june.csv')
        self.assertEqual(alerts['upload-validation-warnings']['count'], 1)
        self.assertIn('2 validation warning', alerts['upload-validation-warnings']['details'][0]['problem'])
        self.assertIn('uploads-awaiting-action', alerts)

    def test_dashboard_returns_one_all_clear_alert_when_nothing_needs_attention(self):
        data = self.dashboard()

        self.assertEqual([alert['id'] for alert in data['alerts']], ['cms-health-clear'])
        self.assertEqual(data['alert_summary'], {
            'total': 0,
            'error': 0,
            'warning': 0,
            'info': 0,
            'success': 1,
        })
        self.assertEqual(data['cards']['system_health'], 'OK')
