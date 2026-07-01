from django.db import migrations, models
from django.db.models import Q


CORE_PLATFORMS = {
    "Apple Music": (True, True),
    "Audiomack": (True, True),
    "Boomplay": (True, False),
    "Spotify": (True, False),
    "YouTube": (True, False),
    "Shazam": (True, False),
}


def apply_methodology(apps, schema_editor):
    Platform = apps.get_model("charts", "Platform")
    PlatformChartEntry = apps.get_model("charts", "PlatformChartEntry")
    MonthlyChartEntry = apps.get_model("charts", "MonthlyChartEntry")
    CertificationRule = apps.get_model("charts", "CertificationRule")
    MethodologySetting = apps.get_model("charts", "MethodologySetting")

    PlatformChartEntry.objects.exclude(position__range=(1, 100)).delete()
    weekly_entries = list(PlatformChartEntry.objects.all().only("id", "position", "points"))
    for entry in weekly_entries:
        entry.points = 101 - entry.position
    if weekly_entries:
        PlatformChartEntry.objects.bulk_update(weekly_entries, ["points"], batch_size=1000)

    for name, (supports_singles, supports_albums) in CORE_PLATFORMS.items():
        Platform.objects.filter(name=name).update(
            chart_size=100,
            points_base=101,
            max_chart_size=50,
            supports_singles=supports_singles,
            supports_albums=supports_albums,
            active=True,
        )
    Platform.objects.filter(name__in=["TikTok", "Radio"]).update(
        supports_singles=False,
        supports_albums=False,
        active=False,
    )

    monthly_entries = list(
        MonthlyChartEntry.objects.select_related("chart").all()
    )
    for entry in monthly_entries:
        if entry.raw_total_points is None:
            entry.raw_total_points = max(int(entry.total_points or 0), 0)
        entry.total_points = 51 - entry.rank if 1 <= entry.rank <= 50 else 0
        entry.platform_max = (
            1
            if entry.platform_id
            else (2 if entry.chart.chart_type == "albums" else 6)
        )
    if monthly_entries:
        MonthlyChartEntry.objects.bulk_update(
            monthly_entries,
            ["raw_total_points", "total_points", "platform_max"],
            batch_size=1000,
        )

    thresholds = {"gold": 200, "platinum": 400, "diamond": 600}
    legacy = {"gold": 5000, "platinum": 10000, "diamond": 20000}
    for level, threshold in thresholds.items():
        rule, created = CertificationRule.objects.get_or_create(
            level=level,
            defaults={"threshold": threshold, "active": True},
        )
        if not created and rule.threshold == legacy[level]:
            rule.threshold = threshold
            rule.active = True
            rule.save(update_fields=["threshold", "active"])

    active = MethodologySetting.objects.filter(is_active=True).order_by("-created_at").first()
    if active:
        config = dict(active.config or {})
        config.update({
            "weekly_points": {"limit": 100, "formula": "101 - rank"},
            "public_points": {"limit": 50, "formula": "51 - rank"},
            "raw_total_points": "sum of fixed weekly Top 100 points; ranking only",
            "total_points": "public Top 50 points; certifications and analytics",
            "combined_artist_source": "Combined Singles Top 50 + Combined Albums Top 50",
            "certification_source": "published Combined Top 50 public points",
        })
        active.version = "v2-top100-top50"
        active.name = "Ngoma Charts Top 100 raw / Top 50 public methodology"
        active.config = config
        active.save(update_fields=["version", "name", "config"])


def reverse_noop(apps, schema_editor):
    # Source workbooks remain available, but the old invalid scores are not
    # recreated automatically.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("charts", "0012_cms_performance_indexes"),
    ]

    operations = [
        migrations.RunPython(apply_methodology, reverse_noop),
        migrations.AlterField(
            model_name="platform",
            name="chart_size",
            field=models.IntegerField(
                default=100,
                help_text="Source charts use the fixed Top 100 methodology",
            ),
        ),
        migrations.AlterField(
            model_name="platform",
            name="points_base",
            field=models.IntegerField(
                default=101,
                help_text="Legacy metadata; weekly scoring is fixed at 101 - rank",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformchartentry",
            constraint=models.CheckConstraint(
                check=Q(position__gte=1, position__lte=100),
                name="weekly_position_top_100",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformchartentry",
            constraint=models.CheckConstraint(
                check=Q(points__gte=1, points__lte=100),
                name="weekly_points_positive_top_100",
            ),
        ),
    ]
