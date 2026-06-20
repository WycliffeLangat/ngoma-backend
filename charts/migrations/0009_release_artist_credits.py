import re

from django.db import migrations, models
import django.db.models.deletion


SEPARATOR_RE = re.compile(r'\s*(?:,|&|\b(?:feat|featuring|ft)\b\.?)\s*', re.IGNORECASE)


def backfill_release_artist_credits(apps, schema_editor):
    Artist = apps.get_model('charts', 'Artist')
    Release = apps.get_model('charts', 'Release')
    ReleaseArtistCredit = apps.get_model('charts', 'ReleaseArtistCredit')
    artists_by_name = {artist.name.strip().casefold(): artist.id for artist in Artist.objects.all()}

    credits = []
    for release in Release.objects.all().iterator():
        credits.append(ReleaseArtistCredit(
            release_id=release.id,
            artist_id=release.artist_id,
            role='primary',
            position=0,
        ))
        seen = {release.artist_id}
        position = 0
        for name in SEPARATOR_RE.split((release.featured_artists or '').strip()):
            artist_id = artists_by_name.get(name.strip().casefold())
            if artist_id and artist_id not in seen:
                credits.append(ReleaseArtistCredit(
                    release_id=release.id,
                    artist_id=artist_id,
                    role='featured',
                    position=position,
                ))
                seen.add(artist_id)
                position += 1
    ReleaseArtistCredit.objects.bulk_create(credits, batch_size=1000, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [('charts', '0008_sync_frontend_chart_data')]

    operations = [
        migrations.CreateModel(
            name='ReleaseArtistCredit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('primary', 'Main artist'), ('featured', 'Featured artist')], max_length=20)),
                ('position', models.PositiveIntegerField(default=0)),
                ('artist', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='release_credits', to='charts.artist')),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='artist_credits', to='charts.release')),
            ],
            options={'ordering': ['role', 'position', 'id']},
        ),
        migrations.AddConstraint(
            model_name='releaseartistcredit',
            constraint=models.UniqueConstraint(fields=('release', 'artist', 'role'), name='unique_release_artist_credit'),
        ),
        migrations.AddConstraint(
            model_name='releaseartistcredit',
            constraint=models.UniqueConstraint(fields=('release', 'role', 'position'), name='unique_release_credit_position'),
        ),
        migrations.RunPython(backfill_release_artist_credits, migrations.RunPython.noop),
    ]
