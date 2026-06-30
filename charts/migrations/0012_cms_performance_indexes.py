from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('charts', '0011_safe_chart_defaults'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='artist',
            index=models.Index(fields=['status', 'name'], name='artist_status_name_idx'),
        ),
        migrations.AddIndex(
            model_name='artist',
            index=models.Index(fields=['country_code'], name='artist_country_code_idx'),
        ),
        migrations.AddIndex(
            model_name='release',
            index=models.Index(fields=['chart_type', 'status', 'title'], name='release_type_status_idx'),
        ),
        migrations.AddIndex(
            model_name='release',
            index=models.Index(fields=['artist', 'status'], name='release_artist_status_idx'),
        ),
        migrations.AddIndex(
            model_name='monthlychart',
            index=models.Index(fields=['is_published', 'status', '-year', '-month'], name='chart_public_period_idx'),
        ),
        migrations.AddIndex(
            model_name='monthlychartentry',
            index=models.Index(fields=['release', 'chart'], name='entry_release_chart_idx'),
        ),
        migrations.AddIndex(
            model_name='monthlychartentry',
            index=models.Index(fields=['chart', 'platform', 'rank'], name='entry_chart_rank_idx'),
        ),
        migrations.AddIndex(
            model_name='chartupload',
            index=models.Index(fields=['status', '-created_at'], name='upload_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['module', '-created_at'], name='audit_module_created_idx'),
        ),
        migrations.AddIndex(
            model_name='dataqualityissue',
            index=models.Index(fields=['status', 'severity'], name='quality_status_sev_idx'),
        ),
    ]
