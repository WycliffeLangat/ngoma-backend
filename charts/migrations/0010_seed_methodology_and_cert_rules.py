"""
Seed a default MethodologySetting and default CertificationRules so the
dashboard alerts are green on a fresh database.  On existing databases the
operation is idempotent: it creates only what is missing.
"""
from django.db import migrations


def seed_defaults(apps, schema_editor):
    MethodologySetting = apps.get_model('charts', 'MethodologySetting')
    CertificationRule  = apps.get_model('charts', 'CertificationRule')

    # Ensure exactly one active methodology exists.
    if not MethodologySetting.objects.filter(is_active=True).exists():
        if not MethodologySetting.objects.exists():
            MethodologySetting.objects.create(
                version='v1',
                name='Ngoma Charts Methodology v1',
                config={},
                is_active=True,
            )
        else:
            # Records exist but none is active – activate the most recent one.
            latest = MethodologySetting.objects.order_by('-created_at').first()
            latest.is_active = True
            latest.save(update_fields=['is_active'])

    # Deactivate any extras so exactly one is active.
    active_ids = list(
        MethodologySetting.objects.filter(is_active=True).order_by('-created_at').values_list('id', flat=True)
    )
    if len(active_ids) > 1:
        MethodologySetting.objects.filter(id__in=active_ids[1:]).update(is_active=False)

    # Default thresholds matching Certification.THRESHOLDS.
    defaults = {'gold': 5000, 'platinum': 10000, 'diamond': 20000}
    for level, threshold in defaults.items():
        obj, created = CertificationRule.objects.get_or_create(
            level=level,
            defaults={'threshold': threshold, 'active': True},
        )
        if not created and not obj.active:
            obj.active = True
            obj.save(update_fields=['active'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('charts', '0009_release_artist_credits'),
    ]

    operations = [
        migrations.RunPython(seed_defaults, noop),
    ]
