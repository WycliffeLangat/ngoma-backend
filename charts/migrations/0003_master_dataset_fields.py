from django.db import migrations, models


def clear_legacy_chart_entries(apps, schema_editor):
    MonthlyChartEntry = apps.get_model("charts", "MonthlyChartEntry")
    MonthlyChartEntry.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("charts", "0002_artist_country_artist_country_code_and_more")]

    operations = [
        migrations.AddField(
            model_name="monthlychartentry",
            name="raw_total_points",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="monthlychartentry",
            name="platform_max",
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name="monthlychartentry",
            name="featured_artists",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="monthlychartentry",
            name="release_year",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="monthlychartentry",
            name="confidence",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
        migrations.RunPython(clear_legacy_chart_entries, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="monthlychartentry",
            unique_together={("chart", "platform", "rank")},
        ),
    ]
