from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from charts.cms_utils import audit, bump_public_revision, harmonize_chart_history, recalculate_certifications
from charts.methodology import normalize_match_key
from charts.models import Artist, ChartType, NormalizationRule, PlatformChartEntry, Release
from charts.pipeline import rebuild_monthly_chart


class Command(BaseCommand):
    help = (
        'Undo the accidental merge of "Baby" by The Ben into "Baby" by Justin Bieber '
        'by moving raw weekly rows back to a separate The Ben release.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply the repair. Without this, only prints a dry run.')
        parser.add_argument('--title', default='Baby')
        parser.add_argument('--correct-artist', default='The Ben')
        parser.add_argument('--keeper-artist', default='Justin Bieber')
        parser.add_argument('--chart-type', default=ChartType.SINGLES)

    def _find_artist(self, name, alternates=()):
        names = [name, *alternates]
        for candidate in names:
            artist = Artist.objects.filter(name__iexact=candidate).first()
            if artist:
                return artist
            artist = Artist.objects.filter(display_name__iexact=candidate).first()
            if artist:
                return artist
        return None

    def _unique_slug(self, text):
        base = slugify(text)[:70] or 'artist'
        slug = base
        index = 2
        while Artist.objects.filter(slug=slug).exists():
            suffix = f'-{index}'
            slug = f'{base[:70 - len(suffix)]}{suffix}'
            index += 1
        return slug

    def _raw_row_matches(self, entry, title, correct_artist, keeper_artist):
        title_key = normalize_match_key(title)
        raw_title_key = normalize_match_key(entry.raw_title)
        if raw_title_key != title_key:
            return False
        raw_artist_key = normalize_match_key(entry.raw_artist)
        correct_key = normalize_match_key(correct_artist)
        keeper_key = normalize_match_key(keeper_artist)
        return correct_key in raw_artist_key and keeper_key not in raw_artist_key

    def handle(self, *args, **options):
        apply = options['apply']
        title = options['title'].strip()
        correct_artist_name = options['correct_artist'].strip()
        keeper_artist_name = options['keeper_artist'].strip()
        chart_type = options['chart_type'].strip()

        if not title or not correct_artist_name or not keeper_artist_name:
            raise CommandError('title, correct-artist, and keeper-artist are required.')

        keeper_artist = self._find_artist(keeper_artist_name, alternates=('Justin Beiber',))
        if not keeper_artist:
            raise CommandError(f'Could not find keeper artist "{keeper_artist_name}".')

        correct_artist = self._find_artist(correct_artist_name)
        if not correct_artist:
            if not apply:
                self.stdout.write(f'Would create artist: {correct_artist_name}')
                correct_artist = Artist(
                    name=correct_artist_name,
                    display_name=correct_artist_name,
                    slug=self._unique_slug(correct_artist_name),
                    country='Rwanda',
                    country_code='RW',
                )
            else:
                correct_artist = Artist.objects.create(
                    name=correct_artist_name,
                    display_name=correct_artist_name,
                    slug=self._unique_slug(correct_artist_name),
                    country='Rwanda',
                    country_code='RW',
                )

        keeper_release = (
            Release.objects
            .filter(title__iexact=title, artist=keeper_artist, chart_type=chart_type)
            .exclude(status='archived')
            .first()
        )
        if not keeper_release:
            raise CommandError(f'Could not find active "{title}" release by {keeper_artist.name}.')

        rows_to_move = [
            entry for entry in (
                PlatformChartEntry.objects
                .filter(release=keeper_release)
                .select_related('upload', 'platform')
                .order_by('upload__year', 'upload__month', 'upload__week', 'platform__name', 'position')
            )
            if self._raw_row_matches(entry, title, correct_artist_name, keeper_artist.name)
        ]

        if not rows_to_move:
            self.stdout.write(self.style.WARNING('No raw weekly rows currently attached to the keeper matched Baby - The Ben.'))
            return

        canonical_title = normalize_match_key(title)
        existing_correct_release = Release.objects.filter(
            artist=correct_artist,
            chart_type=chart_type,
            canonical_title=canonical_title,
        ).first() if getattr(correct_artist, 'pk', None) else None

        periods = sorted({
            (entry.upload.chart_type, entry.upload.year, entry.upload.month)
            for entry in rows_to_move
        })

        self.stdout.write(
            f'Found {len(rows_to_move)} raw weekly row(s) to move from release #{keeper_release.id} '
            f'({keeper_release.title} by {keeper_artist.name}) to {correct_artist_name}.'
        )
        for chart_type_value, year, month in periods:
            self.stdout.write(f'  affected period: {chart_type_value} {year}-{month:02d}')

        if not apply:
            if existing_correct_release:
                self.stdout.write(f'Would use existing release #{existing_correct_release.id}: {existing_correct_release}')
            else:
                self.stdout.write(f'Would create release: {title} by {correct_artist_name}')
            self.stdout.write('Dry run only. Re-run with --apply to change the database.')
            return

        with transaction.atomic():
            correct_release = existing_correct_release
            if correct_release:
                if correct_release.status == 'archived':
                    correct_release.status = 'active'
                    correct_release.save(update_fields=['status', 'updated_at'])
            else:
                correct_release = Release.objects.create(
                    title=title,
                    artist=correct_artist,
                    chart_type=chart_type,
                    canonical_title=canonical_title,
                    country=correct_artist.country or '',
                    country_code=(correct_artist.country_code or '').strip().upper(),
                    status='active',
                )
            for entry in rows_to_move:
                entry.release = correct_release
                entry.save(update_fields=['release'])

            removed_rules, _ = NormalizationRule.objects.filter(
                rule_type='artist',
                raw_value__iexact=correct_artist_name,
                canonical_value__iexact=keeper_artist.name,
            ).delete()

        for chart_type_value, year, month in periods:
            rebuild_monthly_chart(chart_type_value, year, month, harmonize=False)
        harmonize_chart_history(chart_type=chart_type)
        recalculate_certifications(release=keeper_release)
        recalculate_certifications(release=correct_release)
        audit(None, 'repaired_bad_baby_merge', module='releases', new={
            'title': title,
            'correct_artist': correct_artist.name,
            'keeper_artist': keeper_artist.name,
            'keeper_release_id': keeper_release.id,
            'correct_release_id': correct_release.id,
            'platform_rows_moved': len(rows_to_move),
            'periods': periods,
            'normalization_rules_removed': removed_rules,
        })
        bump_public_revision()
        self.stdout.write(self.style.SUCCESS(
            f'Repaired "{title}" by {correct_artist.name}: moved {len(rows_to_move)} weekly row(s) '
            f'to release #{correct_release.id} and rebuilt {len(periods)} period(s).'
        ))
