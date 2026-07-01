from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from .methodology import CERTIFICATION_THRESHOLDS


class Platform(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    short_name = models.CharField(max_length=50, blank=True, default='')
    logo = models.ImageField(upload_to='platforms/', blank=True, null=True)
    color = models.CharField(max_length=7, default='#888888')
    brand_color = models.CharField(max_length=7, blank=True, default='')
    chart_size = models.IntegerField(default=100, help_text="Source charts use the fixed Top 100 methodology")
    max_chart_size = models.IntegerField(default=50, help_text="Maximum chart rows shown/imported in CMS")
    points_base = models.IntegerField(default=101, help_text="Legacy metadata; weekly scoring is fixed at 101 - rank")
    points_method = models.CharField(max_length=100, blank=True, default='rank_descending')
    supports_singles = models.BooleanField(default=True)
    supports_albums = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
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
    display_name = models.CharField(max_length=255, blank=True, default='')
    aliases = models.JSONField(default=list, blank=True)
    city_region = models.CharField(max_length=150, blank=True, default='')
    genre = models.CharField(max_length=150, blank=True, default='')
    biography = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to='artists/', blank=True, null=True)
    spotify_url = models.URLField(blank=True, default='')
    apple_music_url = models.URLField(blank=True, default='')
    youtube_url = models.URLField(blank=True, default='')
    boomplay_url = models.URLField(blank=True, default='')
    audiomack_url = models.URLField(blank=True, default='')
    tiktok_url = models.URLField(blank=True, default='')
    instagram_url = models.URLField(blank=True, default='')
    x_url = models.URLField(blank=True, default='')
    facebook_url = models.URLField(blank=True, default='')
    website_url = models.URLField(blank=True, default='')
    artist_type = models.CharField(max_length=30, blank=True, default='solo')
    status = models.CharField(max_length=30, blank=True, default='active')
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['status', 'name'], name='artist_status_name_idx'),
            models.Index(fields=['country_code'], name='artist_country_code_idx'),
        ]

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
    featured_artists = models.TextField(blank=True, default='')
    credited_artists = models.TextField(blank=True, default='')
    songwriters = models.TextField(blank=True, default='')
    producers = models.TextField(blank=True, default='')
    release_year = models.IntegerField(blank=True, null=True)
    release_date = models.DateField(blank=True, null=True)
    isrc = models.CharField(max_length=50, blank=True, default='')
    upc = models.CharField(max_length=50, blank=True, default='')
    number_of_tracks = models.IntegerField(blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, default='')
    country_code = models.CharField(max_length=2, blank=True, default='')
    genre = models.CharField(max_length=150, blank=True, default='')
    label = models.CharField(max_length=255, blank=True, default='')
    distributor = models.CharField(max_length=255, blank=True, default='')
    cover_image = models.ImageField(upload_to='covers/', blank=True, null=True)
    spotify_url = models.URLField(blank=True, default='')
    apple_music_url = models.URLField(blank=True, default='')
    boomplay_url = models.URLField(blank=True, default='')
    audiomack_url = models.URLField(blank=True, default='')
    youtube_url = models.URLField(blank=True, default='')
    tiktok_url = models.URLField(blank=True, default='')
    shazam_url = models.URLField(blank=True, default='')
    radio_info = models.TextField(blank=True, default='')
    status = models.CharField(max_length=30, blank=True, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['canonical_title', 'artist', 'chart_type']
        ordering = ['title']
        indexes = [
            models.Index(fields=['chart_type', 'status', 'title'], name='release_type_status_idx'),
            models.Index(fields=['artist', 'status'], name='release_artist_status_idx'),
        ]

    def __str__(self):
        return f"{self.title} - {self.artist.name}"

    @property
    def primary_artist_ids(self):
        ids = [credit.artist_id for credit in self.artist_credits.all() if credit.role == 'primary']
        return ids or [self.artist_id]

    @property
    def featured_artist_ids(self):
        return [credit.artist_id for credit in self.artist_credits.all() if credit.role == 'featured']


class ReleaseArtistCredit(models.Model):
    ROLE_CHOICES = [
        ('primary', 'Main artist'),
        ('featured', 'Featured artist'),
    ]

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='artist_credits')
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='release_credits')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['role', 'position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['release', 'artist', 'role'], name='unique_release_artist_credit'),
            models.UniqueConstraint(fields=['release', 'role', 'position'], name='unique_release_credit_position'),
        ]

    def __str__(self):
        return f"{self.release} — {self.get_role_display()}: {self.artist}"


class MonthlyChart(models.Model):
    """A monthly chart period"""
    year = models.IntegerField()
    month = models.IntegerField()
    chart_type = models.CharField(max_length=10, choices=ChartType.choices)
    label = models.CharField(max_length=50, help_text="e.g. 'September 2025'")
    status = models.CharField(max_length=30, default='draft', choices=[('draft','Draft'),('pending_review','Pending review'),('approved','Approved'),('published','Published'),('rejected','Rejected'),('archived','Archived')])
    is_published = models.BooleanField(default=False)
    locked = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)
    published_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='published_charts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['year', 'month', 'chart_type']
        ordering = ['-year', '-month']

        indexes = [
            models.Index(fields=['is_published', 'status', '-year', '-month'], name='chart_public_period_idx'),
        ]
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
        constraints = [
            models.CheckConstraint(
                check=models.Q(position__gte=1, position__lte=100),
                name='weekly_position_top_100',
            ),
            models.CheckConstraint(
                check=models.Q(points__gte=1, points__lte=100),
                name='weekly_points_positive_top_100',
            ),
        ]

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
    raw_total_points = models.IntegerField(null=True, blank=True)
    weeks_on_chart = models.IntegerField(default=1)
    platform_count = models.IntegerField(default=1, help_text="Number of platforms charted on (combined only)")
    platform_max = models.IntegerField(default=1)
    featured_artists = models.TextField(blank=True, default='')
    release_year = models.IntegerField(null=True, blank=True)
    confidence = models.CharField(max_length=30, blank=True, default='')
    peak_rank = models.IntegerField(default=1)
    prev_rank = models.IntegerField(null=True, blank=True, help_text="Rank in previous month")

    class Meta:
        unique_together = ['chart', 'platform', 'rank']
        ordering = ['rank']

        indexes = [
            models.Index(fields=['release', 'chart'], name='entry_release_chart_idx'),
            models.Index(fields=['chart', 'platform', 'rank'], name='entry_chart_rank_idx'),
        ]
    def __str__(self):
        plat = self.platform.name if self.platform else "Combined"
        return f"#{self.rank} {self.release} ({plat})"

    @property
    def movement(self):
        if self.prev_rank is None:
            if not self.pk or not self.chart_id or not self.release_id:
                return 'new'
            appeared_before = MonthlyChartEntry.objects.filter(
                chart__chart_type=self.chart.chart_type,
                chart__is_published=True,
                chart__status='published',
                platform_id=self.platform_id,
                release_id=self.release_id,
                rank__gte=1,
                rank__lte=50,
            ).filter(
                models.Q(chart__year__lt=self.chart.year)
                | models.Q(
                    chart__year=self.chart.year,
                    chart__month__lt=self.chart.month,
                )
            ).exists()
            return 're-entry' if appeared_before else 'new'
        d = self.prev_rank - self.rank
        if d > 0:
            return f'+{d}'
        if d < 0:
            return str(d)
        return '='


class NewsArticle(models.Model):
    CATEGORY_CHOICES = [
        ('chart_news', 'Chart News'),
        ('milestones', 'Milestones'),
        ('new_releases', 'New Releases'),
        ('industry_news', 'Industry News'),
        ('artist_news', 'Artist News'),
        ('awards', 'Awards'),
        ('certifications', 'Certifications'),
        ('records', 'Records'),
        ('interviews', 'Interviews'),
        ('editorials', 'Editorials'),
        ('artist_spotlight', 'Artist Spotlight'),
        ('albums', 'Albums'),
        ('analytics', 'Analytics'),
        ('announcement', 'Announcement'),
    ]

    title = models.CharField(max_length=500)
    slug = models.SlugField(unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    excerpt = models.TextField(blank=True, default='')
    subheadline = models.CharField(max_length=500, blank=True, default='')
    body = models.TextField(blank=True, default='')
    emoji = models.CharField(max_length=10, default='🎵')
    cover_image = models.ImageField(upload_to='news/', blank=True, null=True)
    gallery = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    author = models.CharField(max_length=150, blank=True, default='')
    source_links = models.JSONField(default=list, blank=True)
    seo_title = models.CharField(max_length=255, blank=True, default='')
    seo_description = models.TextField(blank=True, default='')
    status = models.CharField(max_length=30, default='published', choices=[('draft','Draft'),('pending_review','Pending review'),('approved','Approved'),('published','Published'),('rejected','Rejected'),('archived','Archived')])
    is_published = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)
    breaking = models.BooleanField(default=False)
    scheduled_for = models.DateTimeField(blank=True, null=True)
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
        ('gold', 'Gold'),
        ('platinum', 'Platinum'),
        ('diamond', 'Diamond'),
    ]

    # Current Ngoma Charts certification thresholds; labels intentionally avoid the word "Ngoma".
    THRESHOLDS = CERTIFICATION_THRESHOLDS

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='certifications')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    certified_at = models.DateTimeField(auto_now_add=True)
    total_points = models.IntegerField()
    is_official = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    certification_date = models.DateField(blank=True, null=True)
    previous_level = models.CharField(max_length=20, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = ['release', 'level']
        ordering = ['-certified_at']

    def __str__(self):
        return f"{self.release} — {self.get_level_display()}"


class AdminRole(models.TextChoices):
    SUPER_ADMIN = 'super_admin', 'Super Admin'
    ADMIN = 'admin', 'Admin'
    EDITOR = 'editor', 'Editor'
    DATA_EDITOR = 'data_editor', 'Data Editor'
    NEWS_EDITOR = 'news_editor', 'News Editor'
    REVIEWER = 'reviewer', 'Reviewer/Approver'
    VIEWER = 'viewer', 'Viewer'


class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cms_profile')
    role = models.CharField(max_length=30, choices=AdminRole.choices, default=AdminRole.VIEWER)
    phone = models.CharField(max_length=50, blank=True, default='')
    avatar = models.ImageField(upload_to='admin-users/', blank=True, null=True)
    is_active_editor = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.get_username()} — {self.get_role_display()}"


class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=2, blank=True, default='')
    region = models.CharField(max_length=100, blank=True, default='')
    flag = models.CharField(max_length=10, blank=True, default='')
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


class SiteSetting(models.Model):
    key = models.CharField(max_length=120, unique=True)
    value = models.JSONField(default=dict, blank=True)
    group = models.CharField(max_length=80, blank=True, default='general')
    description = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['group', 'key']

    def __str__(self):
        return self.key


class PageContent(models.Model):
    page = models.CharField(max_length=80)
    section = models.CharField(max_length=120)
    title = models.CharField(max_length=255, blank=True, default='')
    content = models.TextField(blank=True, default='')
    data = models.JSONField(default=dict, blank=True)
    is_visible = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ['page', 'section']
        ordering = ['page', 'display_order']

    def __str__(self):
        return f"{self.page}: {self.section}"


class MediaAsset(models.Model):
    FOLDER_CHOICES = [
        ('artists', 'Artists'), ('songs', 'Songs'), ('albums', 'Albums'),
        ('news', 'News'), ('charts', 'Charts'), ('social_cards', 'Social Cards'),
        ('logos', 'Logos'), ('awards', 'Awards'), ('events', 'Events'), ('general', 'General'),
    ]
    title = models.CharField(max_length=255, blank=True, default='')
    file = models.FileField(upload_to='cms-media/')
    folder = models.CharField(max_length=40, choices=FOLDER_CHOICES, default='general')
    alt_text = models.CharField(max_length=255, blank=True, default='')
    usage_notes = models.TextField(blank=True, default='')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.title or self.file.name


class ChartUpload(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('pending_review', 'Pending review'), ('approved', 'Approved'),
        ('published', 'Published'), ('rejected', 'Rejected'), ('archived', 'Archived'), ('rolled_back', 'Rolled back'),
    ]
    chart_type = models.CharField(max_length=10, choices=ChartType.choices)
    year = models.IntegerField()
    month = models.IntegerField()
    platform = models.ForeignKey(Platform, on_delete=models.SET_NULL, null=True, blank=True, help_text='Blank means combined chart')
    file = models.FileField(upload_to='uploads/cms-charts/', blank=True, null=True)
    original_filename = models.CharField(max_length=255, blank=True, default='')
    cleaned_file = models.FileField(upload_to='uploads/cms-cleaned/', blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='draft')
    rows_data = models.JSONField(default=list, blank=True)
    validation_summary = models.JSONField(default=dict, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='chart_uploads')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_chart_uploads')
    published_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cms_published_chart_uploads')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-year', '-month', '-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at'], name='upload_status_created_idx'),
        ]

    def __str__(self):
        target = self.platform.name if self.platform else 'Combined'
        return f"{self.chart_type} {self.month:02d}/{self.year} — {target}"


class AuditLog(models.Model):
    action = models.CharField(max_length=80)
    module = models.CharField(max_length=80, blank=True, default='')
    object_type = models.CharField(max_length=120, blank=True, default='')
    object_id = models.CharField(max_length=80, blank=True, default='')
    object_repr = models.CharField(max_length=255, blank=True, default='')
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default='')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['module', '-created_at'], name='audit_module_created_idx'),
        ]

    def __str__(self):
        who = self.user.get_username() if self.user else 'System'
        return f"{who} {self.action} {self.object_repr or self.object_type}"


class InternalNote(models.Model):
    module = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80)
    note = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


class AdminNotification(models.Model):
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True, default='')
    level = models.CharField(max_length=20, default='info')
    module = models.CharField(max_length=80, blank=True, default='')
    target_url = models.CharField(max_length=255, blank=True, default='')
    is_read = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='cms_notifications')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class BackupRecord(models.Model):
    status = models.CharField(max_length=30, default='created')
    file = models.FileField(upload_to='backups/', blank=True, null=True)
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class DataQualityIssue(models.Model):
    SEVERITY_CHOICES = [('info', 'Info'), ('warning', 'Warning'), ('error', 'Error')]
    module = models.CharField(max_length=80)
    issue_type = models.CharField(max_length=120)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    description = models.TextField()
    object_type = models.CharField(max_length=120, blank=True, default='')
    object_id = models.CharField(max_length=80, blank=True, default='')
    status = models.CharField(max_length=30, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'severity'], name='quality_status_sev_idx'),
        ]


class CertificationRule(models.Model):
    level = models.CharField(max_length=20, choices=Certification.LEVEL_CHOICES, unique=True)
    threshold = models.PositiveIntegerField()
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['threshold']

    def __str__(self):
        return f"{self.get_level_display()} — {self.threshold:,} pts"


class MethodologySetting(models.Model):
    version = models.CharField(max_length=50, default='v1')
    name = models.CharField(max_length=150, default='Default methodology')
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class ArtistMergeLog(models.Model):
    primary_artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='merge_primary_logs')
    merged_artist_name = models.CharField(max_length=255)
    merged_artist_id = models.PositiveIntegerField(blank=True, null=True)
    moved_releases = models.PositiveIntegerField(default=0)
    aliases_added = models.JSONField(default=list, blank=True)
    merged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class PlaceholderModule(models.Model):
    """Phase 2/3 placeholders for future modules such as submissions, newsletter, awards, ads and AI assistant."""
    module = models.CharField(max_length=80)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=30, default='planned')
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['module', 'title']
