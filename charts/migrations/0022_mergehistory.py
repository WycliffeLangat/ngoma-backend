from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('charts', '0021_siteevent_deep_analytics'),
    ]

    operations = [
        migrations.CreateModel(
            name='MergeHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('merge_type', models.CharField(choices=[('artist', 'Artist'), ('release', 'Release')], max_length=20)),
                ('keeper_id', models.PositiveIntegerField()),
                ('keeper_label', models.CharField(blank=True, default='', max_length=255)),
                ('duplicate_id', models.PositiveIntegerField()),
                ('duplicate_label', models.CharField(blank=True, default='', max_length=255)),
                ('snapshot', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('undoable', 'Undoable'), ('undone', 'Undone'), ('blocked', 'Blocked')], default='undoable', max_length=20)),
                ('error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('undone_at', models.DateTimeField(blank=True, null=True)),
                ('merged_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='merge_histories', to=settings.AUTH_USER_MODEL)),
                ('undone_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='undone_merge_histories', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='mergehistory',
            index=models.Index(fields=['merge_type', 'status', '-created_at'], name='mergehist_type_status_idx'),
        ),
        migrations.AddIndex(
            model_name='mergehistory',
            index=models.Index(fields=['keeper_id'], name='mergehist_keeper_idx'),
        ),
        migrations.AddIndex(
            model_name='mergehistory',
            index=models.Index(fields=['duplicate_id'], name='mergehist_duplicate_idx'),
        ),
    ]
