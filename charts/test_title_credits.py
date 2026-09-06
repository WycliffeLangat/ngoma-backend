from django.test import TestCase
from charts.models import Artist, Release
from charts.title_credits import title_featured_names, sync_title_credits
from charts.pipeline import get_or_create_release
from charts.cms_serializers import CmsReleaseSerializer
from charts.models import MonthlyChart, MonthlyChartEntry
from django.core.management import call_command
from io import StringIO


class TitleCreditsTests(TestCase):
    def test_parser(self):
        for marker in ('Featuring', 'feat.', 'ft.', 'with'):
            self.assertEqual(title_featured_names(f'Song ({marker} C & D)'), ['C', 'D'])
        self.assertEqual(title_featured_names('Song feat. C, D'), ['C', 'D'])
        self.assertEqual(title_featured_names('With You (Live)'), [])
        self.assertEqual(title_featured_names('Song (feat. C, D...)'), ['C'])
        self.assertEqual(title_featured_names('Song (feat. C, D\u2026)'), ['C'])
        self.assertEqual(title_featured_names('Song feat. C \u2013 Official Video'), ['C'])
        self.assertEqual(title_featured_names('Song (feat. C) [Official Video]'), ['C'])
        self.assertEqual(title_featured_names('Song (feat. Earth, Wind & Fire)', ['Earth, Wind & Fire']), ['Earth, Wind & Fire'])

    def test_save_and_idempotence(self):
        artist = Artist.objects.create(name='A', slug='a')
        release = Release.objects.create(title='Song (Featuring C & D & A)', canonical_title='song', artist=artist, chart_type='singles')
        self.assertEqual(set(release.artist_credits.values_list('artist__name', flat=True)), {'C', 'D'})
        self.assertEqual(release.featured_artists, 'C & D')
        self.assertFalse(sync_title_credits(release))
        release.title = 'Song (ft. C & E)'
        release.save()
        self.assertEqual(set(release.artist_credits.values_list('artist__name', flat=True)), {'C', 'D', 'E'})

    def test_import_and_cms_preserve_title_credits(self):
        release = get_or_create_release('Song (feat. C & D)', 'A', 'singles')
        get_or_create_release('Song (feat. C & D)', 'A', 'singles')
        serializer = CmsReleaseSerializer(release, data={'featured_artist_ids': []}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        release = serializer.save()
        self.assertEqual(set(release.artist_credits.filter(role='featured').values_list('artist__name', flat=True)), {'C', 'D'})

    def test_historical_backfill_and_dry_run(self):
        artist = Artist.objects.create(name='A', slug='a')
        release = Release.objects.create(title='Song', canonical_title='song', artist=artist, chart_type='singles')
        Release.objects.filter(pk=release.pk).update(title='Song (Featuring C & D)')
        chart = MonthlyChart.objects.create(year=2025, month=9, chart_type='singles')
        entry = MonthlyChartEntry.objects.create(chart=chart, release=release, rank=1, total_points=50, featured_artists='E')
        call_command('backfill_title_credits', stdout=StringIO())
        self.assertFalse(Artist.objects.filter(name='C').exists())
        call_command('backfill_title_credits', apply=True, stdout=StringIO())
        entry.refresh_from_db()
        self.assertEqual(entry.featured_artists, 'E, C & D')
        call_command('backfill_title_credits', apply=True, stdout=StringIO())
        self.assertEqual(release.artist_credits.count(), 2)
