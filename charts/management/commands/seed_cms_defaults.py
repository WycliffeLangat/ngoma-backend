from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from charts.models import CertificationRule, MethodologySetting, SiteSetting, PlaceholderModule, Country, Platform
from charts.methodology import CERTIFICATION_THRESHOLDS


class Command(BaseCommand):
    help = 'Seed Ngoma CMS defaults: certification thresholds, methodology, settings, countries, platforms and future module placeholders.'

    def handle(self, *args, **options):
        for level, threshold in CERTIFICATION_THRESHOLDS.items():
            CertificationRule.objects.update_or_create(level=level, defaults={'threshold': threshold, 'active': True})

        MethodologySetting.objects.update_or_create(
            version='v1-current',
            defaults={
                'name': 'Current Ngoma Charts methodology',
                'is_active': True,
                'config': {
                    'weekly_points': {'limit': 100, 'formula': '101 - rank'},
                    'public_points': {'limit': 50, 'formula': '51 - rank'},
                    'certification_thresholds': CERTIFICATION_THRESHOLDS,
                    'artist_points_source': 'Combined Singles Top 50 + Combined Albums Top 50',
                    'artist_platform_points': {'rank_1': 50, 'rank_50': 1},
                    'artist_entries': 'unique entries',
                    'cross_platform_hit_minimum': {'singles': 2, 'albums': 2},
                    'combined_charts': 'show entries available in dropdown/public selection',
                },
            },
        )

        defaults = {
            'site_name': {'name': 'Ngoma Charts'},
            'theme': {'primary': '#B8860B', 'background': '#FFFFFF', 'cards': '#FFFFFF'},
            'social_links': {
                'facebook': 'https://www.facebook.com/ngomacharts',
                'x': 'https://x.com/Ngoma_Charts',
                'instagram': 'https://www.instagram.com/ngoma_charts/',
            },
            'footer': {'text': '© 2026 Ngoma Charts'},
            'default_chart': {'month': '', 'chart_type': 'singles'},
            'maintenance_mode': {'enabled': False},
        }
        for key, value in defaults.items():
            SiteSetting.objects.update_or_create(key=key, defaults={'value': value, 'group': 'general'})

        countries = [
            ('Kenya', 'KE', 'East Africa'), ('Tanzania', 'TZ', 'East Africa'), ('Uganda', 'UG', 'East Africa'),
            ('Rwanda', 'RW', 'East Africa'), ('Nigeria', 'NG', 'West Africa'), ('South Africa', 'ZA', 'Southern Africa'),
            ('Ghana', 'GH', 'West Africa'), ('Jamaica', 'JM', 'Caribbean'), ('United States', 'US', 'Global'),
            ('United Kingdom', 'GB', 'Global'), ('Canada', 'CA', 'Global'), ('Unknown', '', 'Unknown'),
        ]
        for order, (name, code, region) in enumerate(countries):
            Country.objects.update_or_create(name=name, defaults={'code': code, 'region': region, 'display_order': order, 'active': True})

        platforms = [
            ('Apple Music', 'apple-music', 'Apple', '#FC3C44', True, True, 50),
            ('Spotify', 'spotify', 'Spotify', '#1DB954', True, False, 50),
            ('Boomplay', 'boomplay', 'Boomplay', '#00FFFF', True, False, 50),
            ('Audiomack', 'audiomack', 'Audiomack', '#F68B1F', True, True, 50),
            ('YouTube', 'youtube', 'YouTube', '#FF0000', True, False, 50),
            ('TikTok', 'tiktok', 'TikTok', '#000000', True, False, 50),
            ('Shazam', 'shazam', 'Shazam', '#0088FF', True, False, 50),
            ('Radio', 'radio', 'Radio', '#69716B', True, False, 50),
        ]
        for order, (name, slug, short, color, singles, albums, size) in enumerate(platforms):
            Platform.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'short_name': short,
                    'color': color,
                    'brand_color': color,
                    'chart_size': 100,
                    'points_base': 101,
                    'supports_singles': singles,
                    'supports_albums': albums,
                    'max_chart_size': size,
                    'display_order': order,
                    'active': name not in {'TikTok', 'Radio'},
                },
            )

        for module in ['submissions', 'newsletter', 'awards', 'ads_sponsors', 'ai_assistant', 'advanced_analytics', 'social_cards', 'records', 'year_end', 'backups']:
            PlaceholderModule.objects.get_or_create(module=module, title=module.replace('_', ' ').title(), defaults={'status': 'scaffolded'})

        self.stdout.write(self.style.SUCCESS('CMS defaults seeded.'))
