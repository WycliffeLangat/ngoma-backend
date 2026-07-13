from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('charts', '0016_sync_release_country_to_lead_artist'),
    ]

    operations = [
        migrations.AddField(
            model_name='weeklyupload',
            name='workbook_data',
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='chartupload',
            name='workbook_data',
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
    ]
