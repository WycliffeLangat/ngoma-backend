from django.core.management.base import BaseCommand
from django.db import transaction

from charts.models import Release
from charts.title_credits import sync_title_credits, title_featured_names


class Command(BaseCommand):
    help = 'Add title-featured artists to all historical releases and chart snapshots.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Persist changes (default: dry run).')

    def handle(self, *args, **options):
        count = 0
        with transaction.atomic():
            for release in Release.objects.order_by('pk').iterator():
                if title_featured_names(release.title) and sync_title_credits(release):
                    count += 1
                    self.stdout.write(f'{release.pk}: {release.title} -> {release.featured_artists}')
            if not options['apply']:
                transaction.set_rollback(True)
            if options['apply'] and count:
                from charts.cms_utils import bump_public_revision
                bump_public_revision()
        self.stdout.write(f'{count} releases updated' if options['apply'] else f'{count} releases would be updated (dry run)')
