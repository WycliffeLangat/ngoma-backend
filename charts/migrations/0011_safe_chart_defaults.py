from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('charts', '0010_seed_methodology_and_cert_rules'),
    ]

    operations = [
        migrations.AlterField(
            model_name='monthlychart',
            name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='monthlychart',
            name='status',
            field=models.CharField(
                choices=[('draft', 'Draft'), ('pending_review', 'Pending review'), ('approved', 'Approved'), ('published', 'Published'), ('rejected', 'Rejected'), ('archived', 'Archived')],
                default='draft',
                max_length=30,
            ),
        ),
    ]
