from django.db import migrations


def sync_release_country_to_lead_artist(apps, schema_editor):
    Release = apps.get_model('charts', 'Release')
    ReleaseArtistCredit = apps.get_model('charts', 'ReleaseArtistCredit')

    lead_artist_by_release = {}
    for credit in (
        ReleaseArtistCredit.objects
        .filter(role='primary')
        .select_related('artist')
        .order_by('release_id', 'position', 'id')
    ):
        lead_artist_by_release.setdefault(credit.release_id, credit.artist)

    pending = []
    for release in Release.objects.select_related('artist').iterator():
        artist = lead_artist_by_release.get(release.id) or release.artist
        country = artist.country or ''
        country_code = (artist.country_code or '').strip().upper()
        if release.country == country and release.country_code == country_code:
            continue
        release.country = country
        release.country_code = country_code
        pending.append(release)
        if len(pending) >= 500:
            Release.objects.bulk_update(pending, ['country', 'country_code'])
            pending = []

    if pending:
        Release.objects.bulk_update(pending, ['country', 'country_code'])


class Migration(migrations.Migration):
    dependencies = [
        ('charts', '0015_backfill_full_regional_candidate_pool'),
    ]

    operations = [
        migrations.RunPython(sync_release_country_to_lead_artist, migrations.RunPython.noop),
    ]
