from django.core.management.base import BaseCommand

from charts.jobs import run_worker


class Command(BaseCommand):
    help = 'Process queued chart calculation jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process all currently available jobs, then exit.')
        parser.add_argument('--sleep', type=float, default=2.0, help='Seconds to wait between polling attempts.')
        parser.add_argument('--worker-id', default='', help='Optional stable worker identifier for logs/locks.')

    def handle(self, *args, **options):
        run_worker(
            once=options['once'],
            sleep_seconds=options['sleep'],
            worker_id=options.get('worker_id') or None,
            stdout=self.stdout,
        )
