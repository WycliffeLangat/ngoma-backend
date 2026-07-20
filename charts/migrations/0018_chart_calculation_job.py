from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('charts', '0017_upload_workbook_data'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChartCalculationJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_type', models.CharField(choices=[('process_weekly_upload', 'Process weekly upload'), ('rebuild_month', 'Rebuild monthly chart'), ('publish_chart_upload', 'Publish chart upload'), ('harmonize_chart_history', 'Harmonize chart history')], max_length=64)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Running'), ('succeeded', 'Succeeded'), ('failed', 'Failed')], default='queued', max_length=24)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('result', models.JSONField(blank=True, default=dict)),
                ('error', models.TextField(blank=True, default='')),
                ('dedupe_key', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('priority', models.IntegerField(default=100)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('max_attempts', models.PositiveIntegerField(default=3)),
                ('locked_by', models.CharField(blank=True, default='', max_length=120)),
                ('locked_at', models.DateTimeField(blank=True, null=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chart_calculation_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['priority', 'created_at'],
                'indexes': [models.Index(fields=['status', 'priority', 'created_at'], name='job_status_priority_idx'), models.Index(fields=['job_type', 'status'], name='job_type_status_idx'), models.Index(fields=['locked_at'], name='job_locked_at_idx')],
            },
        ),
    ]
