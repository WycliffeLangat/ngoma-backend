from django.db import models
from django.utils import timezone


class Platform(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    color = models.CharField(max_length=7, default='#888888')
    chart_size = models.IntegerField(default=100, help_text="TopN chart size e.g. 100 or 200")
    points_base = models.IntegerField(default=101, help_text="Points = base - position")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ChartType(models.TextChoices):
    SINGLES = 'singles', 'Singles'
    ALBUMS = 'albums', 'Albums'


class Artist(models.Model):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True)

    # Artist origin fields.
    # country_code should be ISO 3166-1 alpha-2, e.g. KE, TZ, UG, NG, US, GB.
    country = models.CharField(max_length=100, blank=True, default='')
    country_code = models.CharField(max_length=2, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def flag(self):
        """
        Converts an ISO country code into an emoji flag.
        Example: KE -> 🇰🇪, TZ -> 🇹🇿.
        Returns 🌍 when the country code is missing or invalid.
        """
        code = (self.country_code or '').strip().upper()

        if len(code) != 2 or not code.isalpha():
            return '🌍'

        return ''.join(chr(127397 + ord(char)) for char in code)


class Release(models.Model):
    """A song (single) or album"""
    title = models.CharField(max_length=500)
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='releases')
    chart_type = models.CharField(max_length=10, choices=ChartType.choices)
    canonical_title = models.CharField(max_length=500, help_text="Normalized title for deduplication")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['canonical_title', 'artist', 'chart_type']
        ordering = ['title']

    def __str__(self):
        return f"{self.title} - {self.artist.name}"


class MonthlyChart(models.Model):
    """A monthly chart period"""
    year = models.IntegerField()
    month = models.IntegerField()
    chart_type = models.CharField(max_length=10, choices=ChartType.choices)
    label = models.CharField(max_length=50, help_text="e.g. 'October 2024'")
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['year', 'month', 'chart_type']
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.label} ({self.chart_type})"

    def save(self, *args, **kwargs):
        import calendar
        self.label = f"{calendar.month_name[self.month]} {self.year}"
        super().save(*args, **kwargs)


class WeeklyUpload(models.Model):
    """Tracks uploaded raw weekly data files"""
    chart_type = models.CharField(max_length=10, choices=ChartType.choices)
    year = models.IntegerField()
    month = models.IntegerField()
    week = models.IntegerField()
    file = models.FileField(upload_to='uploads/weekly/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    processed = models.BooleanField(default=False)
    processing_notes = models.TextField(blank=True)
    duplicates_dropped = models.IntegerField(default=0)
    entries_processed = models.IntegerField(default=0)

    class Meta:
        unique_together = ['chart_type', 'year', 'month', 'week']
        ordering = ['-year', '-month', '-week']

    def __str__(self):
        return f"{self.chart_type} W{self.week} {self.year}-{self.month:02d}"


class NormalizationRule(models.Model):
    """Stores artist/title normalization rules"""
    rule_type = models.CharField(max_length=10, choices=[('artist', 'Artist'), ('title', 'Title')])
    raw_value = models.CharField(max_length=500)
    canonical_value = models.CharField(max_length=500)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['rule_type', 'raw_value']
        ordering = ['rule_type', 'raw_value']

    def __str__(self):
        return f"[{self.rule_type}] '{self.raw_value}' → '{self.canonical_value}'"


class PlatformChartEntry(models.Model):
    """A single platform chart entry for a given week"""
    upload = models.ForeignKey(WeeklyUpload, on_delete=models.CASCADE, related_name='entries')
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)
    release = models.ForeignKey(Release, on_delete=models.CASCADE)
    position = models.IntegerField()
    points = models.IntegerField()
    raw_title = models.CharField(max_length=500, help_text="Original title from raw data")
    raw_artist = models.CharField(max_length=500, help_text="Original artist from raw data")

    class Meta:
        unique_together = ['upload', 'platform', 'position']
        ordering = ['position']

    def __str__(self):
        return f"{self.platform} #{self.position} {self.release}"


class MonthlyChartEntry(models.Model):
    """Aggregated monthly chart entry (combined across weeks)"""
    chart = models.ForeignKey(MonthlyChart, on_delete=models.CASCADE, related_name='entries')
    platform = models.ForeignKey(
        Platform,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Null = combined chart",
    )
    release = models.ForeignKey(Release, on_delete=models.CASCADE)
    rank = models.IntegerField()
    total_points = models.IntegerField()
    weeks_on_chart = models.IntegerField(default=1)
    platform_count = models.IntegerField(default=1, help_text="Number of platforms charted on (combined only)")
    peak_rank = models.IntegerField(default=1)
    prev_rank = models.IntegerField(null=True, blank=True, help_text="Rank in previous month")

    class Meta:
        unique_together = ['chart', 'platform', 'release']
        ordering = ['rank']

    def __str__(self):
        plat = self.platform.name if self.platform else "Combined"
        return f"#{self.rank} {self.release} ({plat})"

    @property
    def movement(self):
        if self.prev_rank is None:
            return 'new'
        d = self.prev_rank - self.rank
        if d > 0:
            return f'+{d}'
        if d < 0:
            return str(d)
        return '='


class NewsArticle(models.Model):
    CATEGORY_CHOICES = [
        ('chart_news', 'Chart News'),
        ('artist_spotlight', 'Artist Spotlight'),
        ('albums', 'Albums'),
        ('analytics', 'Analytics'),
        ('announcement', 'Announcement'),
    ]

    title = models.CharField(max_length=500)
    slug = models.SlugField(unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    excerpt = models.TextField()
    body = models.TextField()
    emoji = models.CharField(max_length=10, default='🎵')
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    related_release = models.ForeignKey(Release, on_delete=models.SET_NULL, null=True, blank=True)
    related_artist = models.ForeignKey(Artist, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-published_at']

    def __str__(self):
        return self.title


class Certification(models.Model):
    LEVEL_CHOICES = [
        ('ngoma', 'Ngoma'),
        ('gold', 'Ngoma Gold'),
        ('platinum', 'Ngoma Platinum'),
        ('diamond', 'Ngoma Diamond'),
    ]

    # Points thresholds
    THRESHOLDS = {'ngoma': 500, 'gold': 1000, 'platinum': 2000, 'diamond': 5000}

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='certifications')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    certified_at = models.DateTimeField(auto_now_add=True)
    total_points = models.IntegerField()

    class Meta:
        unique_together = ['release', 'level']
        ordering = ['-certified_at']

    def __str__(self):
        return f"{self.release} — {self.get_level_display()}"
