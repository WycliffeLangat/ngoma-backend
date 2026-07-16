from datetime import timedelta

from django.db.models import Count, F, Max, Min, Q
from django.utils import timezone

from .models import (
    AdminNotification,
    AdminProfile,
    Artist,
    BackupRecord,
    Certification,
    CertificationRule,
    ChartUpload,
    Country,
    DataQualityIssue,
    InternalNote,
    MediaAsset,
    MethodologySetting,
    MonthlyChart,
    MonthlyChartEntry,
    NewsArticle,
    PageContent,
    Platform,
    Release,
)


DETAIL_LIMIT = 5
LEVEL_ORDER = {'error': 0, 'warning': 1, 'info': 2, 'success': 3}


def _record_detail(obj, label, problem='', **extra):
    detail = {'id': obj.pk, 'label': label}
    if problem:
        detail['problem'] = problem
    detail.update(extra)
    return detail


def _add_alert(
    alerts,
    *,
    alert_id,
    level,
    category,
    title,
    message,
    count,
    module,
    target_url,
    action,
    details=None,
):
    if count <= 0:
        return
    alerts.append({
        'id': alert_id,
        'level': level,
        'category': category,
        'title': title,
        'message': message,
        'count': count,
        'module': module,
        'target_url': target_url,
        'action': action,
        'details': details or [],
    })


def _field_counts(queryset, field_labels):
    counts = []
    for field, label in field_labels:
        lookup = {field: ''}
        if field.endswith('__isnull'):
            lookup = {field: True}
        count = queryset.filter(**lookup).count()
        if count:
            counts.append({'field': label, 'count': count})
    return counts


def build_dashboard_alerts(user):
    """Return live, actionable CMS health alerts without persisting duplicate notices."""
    alerts = []

    # Existing data-quality reports are surfaced first because somebody explicitly
    # recorded them and expects follow-up.
    open_issues = DataQualityIssue.objects.filter(status='open')
    open_issue_count = open_issues.count()
    if open_issue_count:
        issue_level = 'error' if open_issues.filter(severity='error').exists() else 'warning'
        details = [
            _record_detail(issue, issue.description[:120], issue.issue_type, severity=issue.severity, module=issue.module)
            for issue in open_issues[:DETAIL_LIMIT]
        ]
        _add_alert(
            alerts,
            alert_id='open-data-quality-reports',
            level=issue_level,
            category='data_quality',
            title='Open data-quality reports',
            message=f'{open_issue_count} reported issue(s) still need investigation or resolution.',
            count=open_issue_count,
            module='reports',
            target_url='/reports?status=open',
            action='Review the report details and mark each issue resolved after correction.',
            details=details,
        )

    missing_artist_country = Artist.objects.filter(country='', country_code='').exclude(status='archived')
    count = missing_artist_country.count()
    _add_alert(
        alerts,
        alert_id='artists-missing-country',
        level='warning',
        category='data_quality',
        title='Artists missing country data',
        message=f'{count} active artist(s) have neither a country name nor country code.',
        count=count,
        module='artists',
        target_url='/artists?missing_country=1',
        action='Add a country and ISO two-letter code; release country data will be synchronized where safe.',
        details=[_record_detail(a, a.name, 'Country name and code are both empty') for a in missing_artist_country[:DETAIL_LIMIT]],
    )

    partial_artist_country = Artist.objects.filter(
        Q(country='', country_code__gt='') | Q(country__gt='', country_code='')
    ).exclude(status='archived')
    count = partial_artist_country.count()
    _add_alert(
        alerts,
        alert_id='artists-partial-country',
        level='warning',
        category='data_quality',
        title='Artist country data is incomplete',
        message=f'{count} active artist(s) have only a country name or only a country code.',
        count=count,
        module='artists',
        target_url='/artists',
        action='Complete the missing half of each country value so filtering and flags remain reliable.',
        details=[
            _record_detail(a, a.name, 'Missing country code' if a.country else 'Missing country name', country=a.country, country_code=a.country_code)
            for a in partial_artist_country[:DETAIL_LIMIT]
        ],
    )

    valid_country_codes = list(Country.objects.filter(active=True).exclude(code='').values_list('code', flat=True))
    artist_bad_codes = Artist.objects.exclude(country_code='').exclude(country_code__in=valid_country_codes).exclude(status='archived')
    count = artist_bad_codes.count()
    _add_alert(
        alerts,
        alert_id='artists-unknown-country-code',
        level='warning',
        category='data_quality',
        title='Artist country codes need checking',
        message=f'{count} active artist(s) use a country code that is missing from the active country list.',
        count=count,
        module='artists',
        target_url='/artists',
        action='Correct the code to an active ISO two-letter country code or add the country to CMS settings.',
        details=[_record_detail(a, a.name, f'Unknown code: {a.country_code}', country=a.country) for a in artist_bad_codes[:DETAIL_LIMIT]],
    )

    active_artists = Artist.objects.exclude(status='archived')
    artist_profile_counts = _field_counts(active_artists, [
        ('genre', 'Genre'),
        ('city_region', 'City/region'),
        ('biography', 'Biography'),
        ('image', 'Artist image'),
    ])
    no_artist_link_count = active_artists.filter(
        spotify_url='', apple_music_url='', youtube_url='', boomplay_url='', audiomack_url='', website_url=''
    ).count()
    if no_artist_link_count:
        artist_profile_counts.append({'field': 'Music/profile link', 'count': no_artist_link_count})

    def _artist_missing_fields(artist):
        missing = []
        if not artist.genre:
            missing.append('genre')
        if not artist.city_region:
            missing.append('city/region')
        if not artist.biography:
            missing.append('biography')
        if not artist.image:
            missing.append('image')
        if not (artist.spotify_url or artist.apple_music_url or artist.youtube_url
                or artist.boomplay_url or artist.audiomack_url or artist.website_url):
            missing.append('profile link')
        return ', '.join(missing)

    incomplete_artists = active_artists.filter(
        Q(genre='') | Q(city_region='') | Q(biography='') | Q(image='') |
        Q(spotify_url='', apple_music_url='', youtube_url='', boomplay_url='', audiomack_url='', website_url='')
    )
    _add_alert(
        alerts,
        alert_id='artist-profile-completeness',
        level='info',
        category='content',
        title='Artist profiles could be richer',
        message='Some active artist profiles are missing discoverability or presentation details.',
        count=sum(item['count'] for item in artist_profile_counts),
        module='artists',
        target_url='/artists',
        action='Fill the listed profile fields when reliable information is available.',
        details=[_record_detail(a, a.name, f'Missing {_artist_missing_fields(a)}') for a in incomplete_artists[:DETAIL_LIMIT]],
    )

    active_releases = Release.objects.exclude(status='archived')
    missing_release_country = active_releases.filter(country='', country_code='')
    count = missing_release_country.count()
    _add_alert(
        alerts,
        alert_id='releases-missing-country',
        level='warning',
        category='data_quality',
        title='Releases missing country data',
        message=f'{count} active release(s) have neither a country name nor country code.',
        count=count,
        module='releases',
        target_url='/releases',
        action='Confirm the release country, using the primary artist country only when appropriate.',
        details=[_record_detail(r, f'{r.title} — {r.artist.name}', 'Country name and code are both empty') for r in missing_release_country.select_related('artist')[:DETAIL_LIMIT]],
    )

    partial_release_country = active_releases.filter(
        Q(country='', country_code__gt='') | Q(country__gt='', country_code='')
    )
    count = partial_release_country.count()
    _add_alert(
        alerts,
        alert_id='releases-partial-country',
        level='warning',
        category='data_quality',
        title='Release country data is incomplete',
        message=f'{count} active release(s) have only a country name or only a country code.',
        count=count,
        module='releases',
        target_url='/releases',
        action='Complete the missing country value so public labels and filters agree.',
        details=[
            _record_detail(r, f'{r.title} — {r.artist.name}', 'Missing country code' if r.country else 'Missing country name', country=r.country, country_code=r.country_code)
            for r in partial_release_country.select_related('artist')[:DETAIL_LIMIT]
        ],
    )

    release_bad_codes = active_releases.exclude(country_code='').exclude(country_code__in=valid_country_codes)
    count = release_bad_codes.count()
    _add_alert(
        alerts,
        alert_id='releases-unknown-country-code',
        level='warning',
        category='data_quality',
        title='Release country codes need checking',
        message=f'{count} active release(s) use a code missing from the active country list.',
        count=count,
        module='releases',
        target_url='/releases',
        action='Correct each code or add the corresponding country to CMS settings.',
        details=[_record_detail(r, f'{r.title} — {r.artist.name}', f'Unknown code: {r.country_code}') for r in release_bad_codes.select_related('artist')[:DETAIL_LIMIT]],
    )

    release_metadata_counts = _field_counts(active_releases, [
        ('release_year__isnull', 'Release year'),
        ('release_date__isnull', 'Exact release date'),
        ('genre', 'Genre'),
        ('label', 'Label'),
        ('cover_image', 'Cover image'),
        ('number_of_tracks__isnull', 'Number of tracks'),
    ])
    missing_identifier_count = active_releases.filter(
        Q(chart_type='singles', isrc='') | Q(chart_type='albums', upc='')
    ).count()
    if missing_identifier_count:
        release_metadata_counts.append({'field': 'ISRC/UPC identifier', 'count': missing_identifier_count})
    no_release_link_count = active_releases.filter(
        spotify_url='', apple_music_url='', youtube_url='', boomplay_url='', audiomack_url=''
    ).count()
    if no_release_link_count:
        release_metadata_counts.append({'field': 'Streaming link', 'count': no_release_link_count})

    def _release_missing_fields(release):
        missing = []
        if release.release_year is None:
            missing.append('release year')
        if release.release_date is None:
            missing.append('release date')
        if not release.genre:
            missing.append('genre')
        if not release.label:
            missing.append('label')
        if not release.cover_image:
            missing.append('cover image')
        if release.number_of_tracks is None:
            missing.append('track count')
        if release.chart_type == 'singles' and not release.isrc:
            missing.append('ISRC')
        if release.chart_type == 'albums' and not release.upc:
            missing.append('UPC')
        if not (release.spotify_url or release.apple_music_url or release.youtube_url
                or release.boomplay_url or release.audiomack_url):
            missing.append('streaming link')
        return ', '.join(missing)

    incomplete_releases = active_releases.filter(
        Q(release_year__isnull=True) | Q(release_date__isnull=True) | Q(genre='') | Q(label='') |
        Q(cover_image='') | Q(number_of_tracks__isnull=True) |
        Q(chart_type='singles', isrc='') | Q(chart_type='albums', upc='') |
        Q(spotify_url='', apple_music_url='', youtube_url='', boomplay_url='', audiomack_url='')
    ).select_related('artist')
    _add_alert(
        alerts,
        alert_id='release-metadata-completeness',
        level='info',
        category='content',
        title='Release metadata could be richer',
        message='Some active songs or albums are missing catalog or presentation details.',
        count=sum(item['count'] for item in release_metadata_counts),
        module='releases',
        target_url='/releases',
        action='Fill the listed fields from verified label, distributor, or platform information.',
        details=[_record_detail(r, f'{r.title} — {r.artist.name}', f'Missing {_release_missing_fields(r)}') for r in incomplete_releases[:DETAIL_LIMIT]],
    )

    duplicate_groups = duplicate_artist_groups(limit=50)
    _add_alert(
        alerts,
        alert_id='possible-duplicate-artists',
        level='warning',
        category='data_quality',
        title='Possible duplicate artists',
        message=f'{len(duplicate_groups)} normalized-name group(s) may represent duplicate artists.',
        count=len(duplicate_groups),
        module='artists',
        target_url='/artists?duplicates=1',
        action='Compare aliases, countries, and releases, then merge only confirmed duplicates.',
        details=[{'label': ' / '.join(item['name'] for item in group), 'ids': [item['id'] for item in group]} for group in duplicate_groups[:DETAIL_LIMIT]],
    )

    country_config = Country.objects.filter(Q(code='') | Q(region=''), active=True)
    count = country_config.count()
    _add_alert(
        alerts,
        alert_id='country-settings-incomplete',
        level='info',
        category='configuration',
        title='Country settings are incomplete',
        message=f'{count} active country record(s) are missing a code or region.',
        count=count,
        module='countries',
        target_url='/countries',
        action='Add an ISO two-letter code and reporting region to each active country.',
        details=[_record_detail(c, c.name, ', '.join(name for value, name in [(c.code, 'Missing code'), (c.region, 'Missing region')] if not value)) for c in country_config[:DETAIL_LIMIT]],
    )

    duplicate_codes = list(
        Country.objects.filter(active=True).exclude(code='')
        .values('code').annotate(n=Count('id')).filter(n__gt=1).values_list('code', flat=True)
    )
    countries_with_dup_codes = Country.objects.filter(active=True, code__in=duplicate_codes)
    _add_alert(
        alerts,
        alert_id='countries-duplicate-code',
        level='error',
        category='data_integrity',
        title='Countries share a duplicate code',
        message=f'{len(duplicate_codes)} country code(s) are used by more than one active country.',
        count=len(duplicate_codes),
        module='countries',
        target_url='/countries',
        action='Give each active country its own unique ISO two-letter code.',
        details=[_record_detail(c, c.name, f'Duplicate code: {c.code}') for c in countries_with_dup_codes[:DETAIL_LIMIT]],
    )

    platform_config = Platform.objects.filter(active=True).filter(
        Q(chart_size__lte=0) | Q(max_chart_size__lte=0) | Q(points_base__lte=0) |
        Q(max_chart_size__gt=F('chart_size')) | Q(supports_singles=False, supports_albums=False)
    )
    count = platform_config.count()
    _add_alert(
        alerts,
        alert_id='platform-settings-invalid',
        level='error',
        category='configuration',
        title='Platform chart settings need correction',
        message=f'{count} active platform(s) have chart limits, points, or format support that cannot work safely.',
        count=count,
        module='platforms',
        target_url='/platforms',
        action='Correct chart sizes and points, and enable at least one supported chart type.',
        details=[_record_detail(p, p.name, 'Review size, points base, and supported formats') for p in platform_config[:DETAIL_LIMIT]],
    )

    # Chart workflow and integrity.
    unpublished_charts = MonthlyChart.objects.filter(is_published=False).exclude(status__in=['archived', 'rejected'])
    count = unpublished_charts.count()
    _add_alert(
        alerts,
        alert_id='charts-unpublished',
        level='info',
        category='workflow',
        title='Chart months are not published',
        message=f'{count} chart month(s) remain in draft, review, or approved workflow states.',
        count=count,
        module='charts',
        target_url='/charts?published=0',
        action='Review chart entries and publish records that are complete and approved.',
        details=[_record_detail(c, f'{c.label} — {c.get_chart_type_display()}', f'Status: {c.get_status_display()}') for c in unpublished_charts[:DETAIL_LIMIT]],
    )

    chart_state_mismatch = MonthlyChart.objects.filter(
        Q(is_published=True) & ~Q(status='published') | Q(is_published=False, status='published')
    )
    count = chart_state_mismatch.count()
    _add_alert(
        alerts,
        alert_id='chart-publication-state-mismatch',
        level='error',
        category='data_integrity',
        title='Chart publication state is inconsistent',
        message=f'{count} chart month(s) disagree between status and the published flag.',
        count=count,
        module='charts',
        target_url='/charts',
        action='Publish or unpublish each chart through the CMS workflow to synchronize both values.',
        details=[_record_detail(c, f'{c.label} — {c.chart_type}', f'Status={c.status}; published={c.is_published}') for c in chart_state_mismatch[:DETAIL_LIMIT]],
    )

    empty_charts = MonthlyChart.objects.annotate(entry_count=Count('entries')).filter(entry_count=0).exclude(status='archived')
    count = empty_charts.count()
    _add_alert(
        alerts,
        alert_id='charts-without-entries',
        level='error' if empty_charts.filter(is_published=True).exists() else 'warning',
        category='data_integrity',
        title='Chart months have no entries',
        message=f'{count} non-archived chart month(s) contain no chart rows.',
        count=count,
        module='charts',
        target_url='/charts',
        action='Import or add chart entries; immediately unpublish any empty chart visible to the public.',
        details=[_record_detail(c, f'{c.label} — {c.chart_type}', 'Published with no entries' if c.is_published else 'No entries') for c in empty_charts[:DETAIL_LIMIT]],
    )

    missing_combined = MonthlyChart.objects.annotate(
        entry_count=Count('entries'),
        combined_count=Count('entries', filter=Q(entries__platform__isnull=True)),
    ).filter(entry_count__gt=0, combined_count=0).exclude(status='archived')
    count = missing_combined.count()
    _add_alert(
        alerts,
        alert_id='charts-missing-combined-ranking',
        level='warning',
        category='data_integrity',
        title='Charts are missing a combined ranking',
        message=f'{count} chart month(s) contain platform rows but no combined chart rows.',
        count=count,
        module='charts',
        target_url='/charts',
        action='Generate or import the combined ranking before publication.',
        details=[_record_detail(c, f'{c.label} — {c.chart_type}', f'{c.entry_count} platform row(s), 0 combined') for c in missing_combined[:DETAIL_LIMIT]],
    )

    invalid_entry_checks = [
        ('Rank below 1', MonthlyChartEntry.objects.filter(rank__lt=1)),
        ('Negative points', MonthlyChartEntry.objects.filter(total_points__lt=0)),
        ('Weeks on chart below 1', MonthlyChartEntry.objects.filter(weeks_on_chart__lt=1)),
        ('Platform count exceeds platform maximum', MonthlyChartEntry.objects.filter(platform_count__gt=F('platform_max'))),
        ('Release type differs from chart type', MonthlyChartEntry.objects.exclude(release__chart_type=F('chart__chart_type'))),
        ('Archived release is still on a published chart', MonthlyChartEntry.objects.filter(release__status='archived', chart__is_published=True)),
    ]
    # Details link to the parent chart (not the entry) — that's what the CMS's
    # Chart Entries page can jump straight to and what actually gets fixed.
    invalid_entry_details = []
    for label, qs in invalid_entry_checks:
        for entry in qs.select_related('chart', 'release', 'platform')[:DETAIL_LIMIT]:
            scope = entry.platform.name if entry.platform else 'Combined'
            invalid_entry_details.append({
                'id': entry.chart_id,
                'label': f'{entry.release.title} — {entry.chart.label} ({scope})',
                'problem': label,
            })
    _add_alert(
        alerts,
        alert_id='invalid-chart-entry-values',
        level='error',
        category='data_integrity',
        title='Chart entries contain invalid values',
        message='Some chart rows have impossible values or are attached to the wrong chart type.',
        count=sum(qs.count() for _, qs in invalid_entry_checks),
        module='chart_entries',
        target_url='/chart-entries',
        action='Correct every listed entry before relying on rankings or points totals.',
        details=invalid_entry_details[:DETAIL_LIMIT],
    )

    rank_sets = MonthlyChartEntry.objects.values('chart_id', 'platform_id').annotate(
        row_count=Count('id'), minimum_rank=Min('rank'), maximum_rank=Max('rank')
    )
    rank_gaps = [row for row in rank_sets if row['minimum_rank'] != 1 or row['maximum_rank'] != row['row_count']]
    rank_gap_details = []
    for row in rank_gaps[:DETAIL_LIMIT]:
        chart = MonthlyChart.objects.filter(pk=row['chart_id']).first()
        platform = Platform.objects.filter(pk=row['platform_id']).first() if row['platform_id'] else None
        rank_gap_details.append({
            'id': row['chart_id'],
            'label': f'{chart.label if chart else "Chart"} — {platform.name if platform else "Combined"}',
            'problem': f'{row["row_count"]} rows span ranks {row["minimum_rank"]}–{row["maximum_rank"]}',
        })
    _add_alert(
        alerts,
        alert_id='chart-rank-gaps',
        level='warning',
        category='data_integrity',
        title='Chart rankings contain gaps',
        message=f'{len(rank_gaps)} chart/platform ranking set(s) are not numbered consecutively from 1.',
        count=len(rank_gaps),
        module='chart_entries',
        target_url='/charts',
        action='Review the affected ranking and use reorder after confirming the intended row order.',
        details=rank_gap_details,
    )

    pending_uploads = ChartUpload.objects.filter(status__in=['draft', 'pending_review', 'approved'])
    count = pending_uploads.count()
    _add_alert(
        alerts,
        alert_id='uploads-awaiting-action',
        level='warning' if pending_uploads.filter(status='pending_review').exists() else 'info',
        category='workflow',
        title='Chart uploads await action',
        message=f'{count} chart upload(s) are drafted, awaiting review, or approved but not published.',
        count=count,
        module='chart_uploads',
        target_url='/chart-uploads',
        action='Resolve validation findings, review pending files, and publish approved uploads.',
        details=[_record_detail(u, u.original_filename or str(u), f'Status: {u.get_status_display()}', rows=u.row_count) for u in pending_uploads[:DETAIL_LIMIT]],
    )

    upload_error_details = []
    upload_warning_details = []
    for upload in ChartUpload.objects.exclude(status__in=['archived', 'rolled_back']):
        summary = upload.validation_summary or {}
        error_count = summary.get('error_count', len(summary.get('errors', []))) or 0
        warning_count = summary.get('warning_count', len(summary.get('warnings', []))) or 0
        if error_count:
            upload_error_details.append(_record_detail(upload, upload.original_filename or str(upload), f'{error_count} validation error(s)', status=upload.status))
        if warning_count:
            upload_warning_details.append(_record_detail(upload, upload.original_filename or str(upload), f'{warning_count} validation warning(s)', status=upload.status))
    _add_alert(
        alerts,
        alert_id='upload-validation-errors',
        level='error',
        category='data_integrity',
        title='Chart uploads have validation errors',
        message=f'{len(upload_error_details)} active upload(s) contain errors that can block safe publication.',
        count=len(upload_error_details),
        module='chart_uploads',
        target_url='/chart-uploads',
        action='Open each upload, correct the row-level errors, then revalidate.',
        details=upload_error_details[:DETAIL_LIMIT],
    )
    _add_alert(
        alerts,
        alert_id='upload-validation-warnings',
        level='warning',
        category='data_quality',
        title='Chart uploads have validation warnings',
        message=f'{len(upload_warning_details)} active upload(s) contain details that need a human check.',
        count=len(upload_warning_details),
        module='chart_uploads',
        target_url='/chart-uploads',
        action='Review every warning and confirm that any exception is intentional before approval.',
        details=upload_warning_details[:DETAIL_LIMIT],
    )

    # Editorial workflow and published-content readiness.
    pending_news = NewsArticle.objects.filter(status__in=['draft', 'pending_review', 'approved'])
    count = pending_news.count()
    _add_alert(
        alerts,
        alert_id='news-awaiting-action',
        level='info',
        category='workflow',
        title='News articles await editorial action',
        message=f'{count} article(s) are drafted, pending review, or approved but not published.',
        count=count,
        module='news',
        target_url='/news',
        action='Complete, review, schedule, or publish each article as appropriate.',
        details=[_record_detail(n, n.title, f'Status: {n.get_status_display()}') for n in pending_news[:DETAIL_LIMIT]],
    )

    due_scheduled_news = NewsArticle.objects.filter(
        scheduled_for__isnull=False, scheduled_for__lte=timezone.now(), is_published=False
    ).exclude(status__in=['archived', 'rejected'])
    count = due_scheduled_news.count()
    _add_alert(
        alerts,
        alert_id='scheduled-news-overdue',
        level='warning',
        category='workflow',
        title='Scheduled news is overdue',
        message=f'{count} article(s) passed their scheduled publish time but remain unpublished.',
        count=count,
        module='news',
        target_url='/news',
        action='Publish now, reschedule, or cancel the schedule after editorial review.',
        details=[_record_detail(n, n.title, f'Was due {n.scheduled_for.isoformat()}') for n in due_scheduled_news[:DETAIL_LIMIT]],
    )

    news_state_mismatch = NewsArticle.objects.filter(
        Q(is_published=True) & ~Q(status='published') | Q(is_published=False, status='published')
    )
    count = news_state_mismatch.count()
    _add_alert(
        alerts,
        alert_id='news-publication-state-mismatch',
        level='error',
        category='data_integrity',
        title='News publication state is inconsistent',
        message=f'{count} article(s) disagree between status and the published flag.',
        count=count,
        module='news',
        target_url='/news',
        action='Publish or unpublish through the CMS workflow so both values agree.',
        details=[_record_detail(n, n.title, f'Status={n.status}; published={n.is_published}') for n in news_state_mismatch[:DETAIL_LIMIT]],
    )

    published_news = NewsArticle.objects.filter(status='published', is_published=True)
    news_content_counts = _field_counts(published_news, [
        ('excerpt', 'Excerpt'),
        ('body', 'Article body'),
        ('author', 'Author'),
        ('cover_image', 'Cover image'),
        ('seo_title', 'SEO title'),
        ('seo_description', 'SEO description'),
    ])

    def _news_missing_fields(article):
        missing = []
        if not article.excerpt:
            missing.append('excerpt')
        if not article.body:
            missing.append('body')
        if not article.author:
            missing.append('author')
        if not article.cover_image:
            missing.append('cover image')
        if not article.seo_title:
            missing.append('SEO title')
        if not article.seo_description:
            missing.append('SEO description')
        return ', '.join(missing)

    incomplete_news = published_news.filter(
        Q(excerpt='') | Q(body='') | Q(author='') | Q(cover_image='') | Q(seo_title='') | Q(seo_description='')
    )
    _add_alert(
        alerts,
        alert_id='published-news-completeness',
        level='warning',
        category='content',
        title='Published news is missing details',
        message='Some live articles are missing editorial, visual, attribution, or search metadata.',
        count=sum(item['count'] for item in news_content_counts),
        module='news',
        target_url='/news?status=published',
        action='Complete the listed fields, prioritizing missing body, author, and cover image.',
        details=[_record_detail(n, n.title, f'Missing {_news_missing_fields(n)}') for n in incomplete_news[:DETAIL_LIMIT]],
    )

    invalid_certification_checks = [
        ('Points are zero or negative', Certification.objects.filter(total_points__lte=0)),
        ('Certification date is in the future', Certification.objects.filter(certification_date__gt=timezone.now().date())),
        ('Underlying release is archived but certification is visible', Certification.objects.filter(release__status='archived', is_hidden=False)),
    ]
    invalid_certification_details = [
        _record_detail(c, f'{c.release.title} — {c.get_level_display()}', label)
        for label, qs in invalid_certification_checks
        for c in qs.select_related('release')[:DETAIL_LIMIT]
    ]
    _add_alert(
        alerts,
        alert_id='certifications-invalid-values',
        level='error',
        category='data_integrity',
        title='Certifications contain invalid values',
        message='Some certifications have impossible points, a future certification date, or belong to an archived release.',
        count=sum(qs.count() for _, qs in invalid_certification_checks),
        module='certifications',
        target_url='/certifications',
        action='Correct or hide each listed certification.',
        details=invalid_certification_details[:DETAIL_LIMIT],
    )

    below_threshold = []
    below_threshold_count = 0
    for rule in CertificationRule.objects.filter(active=True):
        matching = Certification.objects.filter(level=rule.level, total_points__lt=rule.threshold)
        below_threshold_count += matching.count()
        for certification in matching.select_related('release')[:DETAIL_LIMIT]:
            below_threshold.append(_record_detail(
                certification,
                f'{certification.release.title} — {certification.get_level_display()}',
                f'{certification.total_points:,} points; threshold is {rule.threshold:,}',
            ))
    _add_alert(
        alerts,
        alert_id='certifications-below-threshold',
        level='error',
        category='data_integrity',
        title='Certifications fall below their threshold',
        message=f'{below_threshold_count} certification(s) have fewer points than the active rule requires.',
        count=below_threshold_count,
        module='certifications',
        target_url='/certifications',
        action='Recalculate certifications or correct the points/rule before keeping these awards visible.',
        details=below_threshold[:DETAIL_LIMIT],
    )

    active_rules = list(CertificationRule.objects.filter(active=True).order_by('threshold'))
    rule_problems = []
    if not active_rules:
        rule_problems.append({'label': 'No active certification rules', 'count': 1})
    if len(active_rules) < len(Certification.LEVEL_CHOICES):
        missing_levels = sorted(set(dict(Certification.LEVEL_CHOICES)) - {r.level for r in active_rules})
        if missing_levels:
            rule_problems.append({'label': 'Missing active level(s)', 'values': missing_levels, 'count': len(missing_levels)})
    threshold_conflicts = [(a, b) for a, b in zip(active_rules, active_rules[1:]) if a.threshold >= b.threshold]
    if threshold_conflicts:
        rule_problems.append({'label': 'Thresholds are not strictly increasing', 'count': len(threshold_conflicts)})
    conflict_details = [
        _record_detail(a, f'{a.get_level_display()} rule ({a.threshold:,} pts)', f'Not below {b.get_level_display()} ({b.threshold:,} pts)')
        for a, b in threshold_conflicts
    ]
    _add_alert(
        alerts,
        alert_id='certification-rule-configuration',
        level='error',
        category='configuration',
        title='Certification rules need configuration',
        message='Certification levels are missing or their thresholds do not increase cleanly.',
        count=sum(item['count'] for item in rule_problems),
        module='certification_rules',
        target_url='/certification-rules',
        action='Keep one active rule per level and ensure higher awards require strictly more points.',
        details=(conflict_details + rule_problems)[:DETAIL_LIMIT],
    )

    visible_empty_content = PageContent.objects.filter(is_visible=True).filter(
        Q(title='', content='') & (Q(data={}) | Q(data__isnull=True))
    )
    count = visible_empty_content.count()
    _add_alert(
        alerts,
        alert_id='visible-page-content-empty',
        level='warning',
        category='content',
        title='Visible page sections are empty',
        message=f'{count} visible page section(s) have no title, text, or structured data.',
        count=count,
        module='page_content',
        target_url='/page-content',
        action='Add content or hide the section until it is ready.',
        details=[_record_detail(p, f'{p.page}: {p.section}', 'Visible section has no content') for p in visible_empty_content[:DETAIL_LIMIT]],
    )

    media_details = []
    media_missing_alt = MediaAsset.objects.filter(is_archived=False, alt_text='').count()
    media_missing_title = MediaAsset.objects.filter(is_archived=False, title='').count()
    if media_missing_alt:
        media_details.append({'field': 'Alternative text', 'count': media_missing_alt})
    if media_missing_title:
        media_details.append({'field': 'Descriptive title', 'count': media_missing_title})
    incomplete_media = MediaAsset.objects.filter(is_archived=False).filter(Q(alt_text='') | Q(title=''))
    _add_alert(
        alerts,
        alert_id='media-metadata-incomplete',
        level='info',
        category='content',
        title='Media assets need accessibility details',
        message='Some active media assets are missing a descriptive title or alternative text.',
        count=sum(item['count'] for item in media_details),
        module='media',
        target_url='/media',
        action='Add concise, meaningful titles and alt text to each reusable image.',
        details=[
            _record_detail(
                m, m.title or m.file.name,
                f"Missing {', '.join(f for f, present in [('title', m.title), ('alt text', m.alt_text)] if not present)}",
            )
            for m in incomplete_media[:DETAIL_LIMIT]
        ],
    )

    active_methodologies = MethodologySetting.objects.filter(is_active=True)
    active_methodology_count = active_methodologies.count()
    if active_methodology_count != 1:
        _add_alert(
            alerts,
            alert_id='methodology-active-count',
            level='error' if active_methodology_count == 0 else 'warning',
            category='configuration',
            title='Active methodology needs checking',
            message=f'{active_methodology_count} methodologies are active; exactly one should define current calculations.',
            count=1,
            module='methodology',
            target_url='/methodology',
            action='Activate the current methodology and deactivate superseded versions.',
            details=[_record_detail(m, f'{m.version} — {m.name}', 'Currently active') for m in active_methodologies[:DETAIL_LIMIT]],
        )

    inactive_since = timezone.now() - timedelta(days=60)
    inactive_editors = AdminProfile.objects.filter(
        user__is_active=True, is_active_editor=True,
    ).exclude(role='viewer').filter(
        Q(last_seen_at__isnull=True) | Q(last_seen_at__lt=inactive_since)
    ).select_related('user')
    count = inactive_editors.count()
    _add_alert(
        alerts,
        alert_id='inactive-editor-accounts',
        level='info',
        category='system',
        title='Editor accounts have gone quiet',
        message=f'{count} editor/admin account(s) have not been seen in the CMS for 60+ days, or never.',
        count=count,
        module='users',
        target_url='/users',
        action='Confirm the person still needs CMS access, or deactivate the account.',
        details=[
            _record_detail(
                p.user, p.user.get_username(),
                'Never seen in the CMS' if not p.last_seen_at else f'Last seen {p.last_seen_at.date().isoformat()}',
            )
            for p in inactive_editors[:DETAIL_LIMIT]
        ],
    )

    unresolved_notes = InternalNote.objects.filter(is_resolved=False)
    count = unresolved_notes.count()
    _add_alert(
        alerts,
        alert_id='internal-notes-unresolved',
        level='info',
        category='workflow',
        title='Internal notes remain unresolved',
        message=f'{count} internal note(s) still need follow-up.',
        count=count,
        module='notes',
        target_url='/notes?resolved=0',
        action='Review the note, complete the requested follow-up, and mark it resolved.',
        details=[_record_detail(n, n.note[:120], f'{n.module} #{n.object_id}') for n in unresolved_notes[:DETAIL_LIMIT]],
    )

    unread_notifications = AdminNotification.objects.filter(
        Q(user=user) | Q(user__isnull=True), is_read=False
    )
    count = unread_notifications.count()
    _add_alert(
        alerts,
        alert_id='admin-notifications-unread',
        level='info',
        category='notification',
        title='Unread CMS notifications',
        message=f'{count} notification(s) have not been read.',
        count=count,
        module='notifications',
        target_url='/notifications?read=0',
        action='Open the notifications panel and acknowledge each relevant update.',
        details=[_record_detail(n, n.title, n.message[:120], level=n.level) for n in unread_notifications[:DETAIL_LIMIT]],
    )

    latest_backup = BackupRecord.objects.order_by('-created_at').first()
    if latest_backup is None:
        _add_alert(
            alerts,
            alert_id='backup-missing',
            level='warning',
            category='system',
            title='No CMS backup is recorded',
            message='The CMS has no backup record to confirm recoverability.',
            count=1,
            module='backups',
            target_url='/backups',
            action='Create and verify a backup, then document the restore location.',
            details=[{'label': 'No backup history found'}],
        )
    else:
        backup_age = timezone.now() - latest_backup.created_at
        if latest_backup.status not in {'created', 'completed', 'success'}:
            _add_alert(
                alerts,
                alert_id='latest-backup-failed',
                level='error',
                category='system',
                title='Latest CMS backup was not successful',
                message=f'The latest backup status is “{latest_backup.status}”.',
                count=1,
                module='backups',
                target_url='/backups',
                action='Investigate the backup failure and create a verified replacement.',
                details=[_record_detail(latest_backup, latest_backup.created_at.isoformat(), latest_backup.notes or latest_backup.status)],
            )
        elif backup_age > timedelta(days=30):
            _add_alert(
                alerts,
                alert_id='backup-stale',
                level='warning',
                category='system',
                title='CMS backup is stale',
                message=f'The latest recorded backup is {backup_age.days} days old.',
                count=1,
                module='backups',
                target_url='/backups',
                action='Create and verify a fresh backup.',
                details=[_record_detail(latest_backup, latest_backup.created_at.isoformat(), f'{backup_age.days} days old')],
            )

    if not alerts:
        alerts.append({
            'id': 'cms-health-clear',
            'level': 'success',
            'category': 'system',
            'title': 'CMS checks are clear',
            'message': 'No workflow, data-quality, content, configuration, or backup issues were detected.',
            'count': 0,
            'module': 'dashboard',
            'target_url': '/dashboard',
            'action': 'No action is needed.',
            'details': [],
        })

    alerts.sort(key=lambda alert: (LEVEL_ORDER.get(alert['level'], 99), alert['title']))
    return alerts


def summarize_alerts(alerts):
    summary = {'total': 0, 'error': 0, 'warning': 0, 'info': 0, 'success': 0}
    for alert in alerts:
        level = alert.get('level', 'info')
        summary[level] = summary.get(level, 0) + 1
        if level != 'success':
            summary['total'] += 1
    return summary


def duplicate_artist_groups(limit=100):
    """Kept local to avoid a circular import from cms_views."""
    import re
    import unicodedata

    buckets = {}
    artists = Artist.objects.exclude(status='archived').only('id', 'name', 'country', 'country_code')
    for artist in artists:
        value = unicodedata.normalize('NFKD', artist.name or '').encode('ascii', 'ignore').decode('ascii')
        key = re.sub(r'[^a-z0-9]+', '', value.lower())
        buckets.setdefault(key, []).append({
            'id': artist.id,
            'name': artist.name,
            'country': artist.country,
            'country_code': artist.country_code,
        })
    groups = [items for items in buckets.values() if len(items) > 1]
    groups.sort(key=len, reverse=True)
    return groups[:limit]
