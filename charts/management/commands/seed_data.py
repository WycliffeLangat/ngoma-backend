"""
Loads chart data from full_data.json and full_analytics.json into the database.
Run after migrations on first deploy:
    python manage.py seed_data
"""
import json
import os
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from charts.models import (
    Platform, Artist, Release, MonthlyChart, MonthlyChartEntry,
    NewsArticle, Certification, ChartType
)


PLATFORM_DATA = [
    ('Apple Music', 'apple-music', '#FC3C44', 100, 101),
    ('Audiomack', 'audiomack', '#F68B1F', 100, 101),
    ('Boomplay', 'boomplay', '#2DB04A', 100, 101),
    ('Spotify', 'spotify', '#1DB954', 50, 101),
    ('YouTube', 'youtube', '#FF0000', 100, 101),
    ('Shazam', 'shazam', '#0088FF', 100, 101),
]

MONTH_MAP = {
    'October 2024': (2024, 10),
    'November 2024': (2024, 11),
    'December 2024': (2024, 12),
}

PLATFORM_NAME_MAP = {
    'APPLE MUSIC': 'Apple Music',
    'AUDIOMACK': 'Audiomack',
    'BOOMPLAY': 'Boomplay',
    'SPOTIFY': 'Spotify',
    'YOUTUBE': 'YouTube',
    'SHAZAM': 'Shazam',
}


def safe_slug(text, length=50):
    s = slugify(text)[:length] or 'unknown'
    return s


def get_or_create_artist(name, slugs_used):
    base = safe_slug(name)
    slug = base
    i = 1
    while slug in slugs_used and slugs_used[slug] != name:
        slug = f"{base}-{i}"
        i += 1
    artist, created = Artist.objects.get_or_create(name=name, defaults={'slug': slug})
    slugs_used[artist.slug] = artist.name
    return artist


def get_or_create_release(title, artist, chart_type):
    canonical = title.lower().strip()
    release, _ = Release.objects.get_or_create(
        canonical_title=canonical, artist=artist, chart_type=chart_type,
        defaults={'title': title}
    )
    return release


class Command(BaseCommand):
    help = 'Seed the database with chart data from full_data.json'

    def add_arguments(self, parser):
        parser.add_argument('--data-file', type=str,
                            default='charts/seed_data/full_data.json',
                            help='Path to full_data.json')
        parser.add_argument('--clear', action='store_true',
                            help='Clear existing chart data before seeding')

    @transaction.atomic
    def handle(self, *args, **options):
        data_file = options['data_file']
        if not os.path.exists(data_file):
            self.stdout.write(self.style.ERROR(f'Data file not found: {data_file}'))
            return

        # Seed platforms
        self.stdout.write('Seeding platforms...')
        for name, slug, color, size, base in PLATFORM_DATA:
            Platform.objects.update_or_create(
                name=name,
                defaults={'slug': slug, 'color': color, 'chart_size': size,
                          'points_base': base, 'active': True}
            )
        platforms = {p.name: p for p in Platform.objects.all()}

        if options['clear']:
            self.stdout.write('Clearing existing chart entries...')
            MonthlyChartEntry.objects.all().delete()
            MonthlyChart.objects.all().delete()
            Release.objects.all().delete()
            Artist.objects.all().delete()
            Certification.objects.all().delete()

        # Load data
        with open(data_file) as f:
            data = json.load(f)

        slugs_used = {}

        for chart_type_key in ('singles', 'albums'):
            ct_value = ChartType.SINGLES if chart_type_key == 'singles' else ChartType.ALBUMS
            self.stdout.write(f'\nProcessing {chart_type_key}...')

            # Combined entries
            for month_label, entries in data[chart_type_key]['combined'].items():
                year, month_num = MONTH_MAP[month_label]
                chart, _ = MonthlyChart.objects.get_or_create(
                    year=year, month=month_num, chart_type=ct_value,
                    defaults={'label': month_label}
                )
                for e in entries:
                    artist = get_or_create_artist(e['a'], slugs_used)
                    release = get_or_create_release(e['t'], artist, ct_value)
                    plat_count = int(e['pl'].split('/')[0]) if e.get('pl') else 1
                    MonthlyChartEntry.objects.update_or_create(
                        chart=chart, platform=None, release=release,
                        defaults={
                            'rank': e['r'], 'total_points': e['p'],
                            'platform_count': plat_count,
                            'prev_rank': e.get('pr'),
                            'peak_rank': e['r'],
                        }
                    )
                self.stdout.write(f'  {chart_type_key} combined {month_label}: {len(entries)} entries')

            # Per-platform entries
            for plat_key, months in data[chart_type_key]['platforms'].items():
                plat_name = PLATFORM_NAME_MAP.get(plat_key, plat_key)
                if plat_name not in platforms:
                    continue
                plat = platforms[plat_name]
                for month_label, entries in months.items():
                    year, month_num = MONTH_MAP[month_label]
                    chart = MonthlyChart.objects.get(year=year, month=month_num, chart_type=ct_value)
                    for e in entries:
                        artist = get_or_create_artist(e['a'], slugs_used)
                        release = get_or_create_release(e['t'], artist, ct_value)
                        MonthlyChartEntry.objects.update_or_create(
                            chart=chart, platform=plat, release=release,
                            defaults={
                                'rank': e['r'], 'total_points': e['p'],
                                'platform_count': 1, 'peak_rank': e['r'],
                            }
                        )

        # Award certifications
        from charts.pipeline import award_certifications
        self.stdout.write('\nAwarding certifications...')
        award_certifications(ChartType.SINGLES)
        award_certifications(ChartType.ALBUMS)

        # Seed news
        self.stdout.write('\nSeeding news articles...')
        seed_news()

        self.stdout.write(self.style.SUCCESS('\n✓ Seed complete!'))
        self.stdout.write(f'  {Artist.objects.count()} artists')
        self.stdout.write(f'  {Release.objects.count()} releases')
        self.stdout.write(f'  {MonthlyChartEntry.objects.count()} chart entries')
        self.stdout.write(f'  {Certification.objects.count()} certifications')
        self.stdout.write(f'  {NewsArticle.objects.count()} news articles')


def seed_news():
    from datetime import datetime
    articles = [
        {'date':'2024-12-31','cat':'chart_news','emoji':'🎵','title':"Olodumare Dethrones Bensoul to Claim December #1",
         'excerpt':"After two consecutive months at the top, Bensoul's Extra Pressure falls to #3 as Joel Lwaga's Olodumare storms to #1 with 2,286 points across all six platforms.",
         'body':"Joel Lwaga's Olodumare made history in December 2024, becoming the first song to dethrone Bensoul's Extra Pressure from the #1 spot since Ngoma Charts launched."},
        {'date':'2024-12-15','cat':'artist_spotlight','emoji':'🌟','title':"Iyanii: Q4's Fastest-Rising Artist",
         'excerpt':"Kifo Cha Mende rose from outside the Top 20 in October to #2 in December — the biggest month-on-month rise of any song in Q4 2024.",
         'body':"Iyanii's Kifo Cha Mende is the breakout story of Q4 2024."},
        {'date':'2024-12-05','cat':'albums','emoji':'💿','title':"GNX Tops Kenya's Albums Chart",
         'excerpt':"Kendrick Lamar's surprise album lands at #1 on both Apple Music and Audiomack Kenya in December, displacing Asake's Lungu Boy.",
         'body':"GNX edged out Marioo's The Godson by just 12 points (1,556 vs 1,544) in one of the closest #1 races of the year."},
        {'date':'2024-10-31','cat':'announcement','emoji':'🚀','title':"Ngoma Charts Launches",
         'excerpt':"Kenya's official multi-platform music ranking system debuts with Bensoul's Extra Pressure as the inaugural #1.",
         'body':"Ngoma Charts uses a 101-point system: #1 earns 100 points, #100 earns 1 point. Albums use a 201-point scale across the Top 200."},
    ]
    for a in articles:
        NewsArticle.objects.update_or_create(
            slug=safe_slug(a['title'], 80),
            defaults={
                'title': a['title'], 'category': a['cat'],
                'excerpt': a['excerpt'], 'body': a['body'], 'emoji': a['emoji'],
                'is_published': True,
                'published_at': datetime.fromisoformat(a['date']),
            }
        )
