from django.contrib import admin
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from .models import *
from .pipeline import process_weekly_upload, rebuild_monthly_chart


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ['name', 'colored_dot', 'chart_size', 'points_base', 'active']
    list_editable = ['active']

    def colored_dot(self, obj):
        return format_html('<span style="color:{};font-size:20px">●</span>', obj.color)
    colored_dot.short_description = 'Color'


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'release_count']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}

    def release_count(self, obj):
        return obj.releases.count()
    release_count.short_description = 'Releases'


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ['title', 'artist', 'chart_type', 'certification_badges']
    list_filter = ['chart_type']
    search_fields = ['title', 'artist__name']
    raw_id_fields = ['artist']

    def certification_badges(self, obj):
        certs = obj.certifications.all()
        badges = {
            'gold': '🥇', 'platinum': '🪙', 'diamond': '💎'
        }
        return ' '.join([badges.get(c.level, '') for c in certs])
    certification_badges.short_description = 'Certs'


class PlatformChartEntryInline(admin.TabularInline):
    model = PlatformChartEntry
    extra = 0
    readonly_fields = ['platform', 'release', 'position', 'points', 'raw_title', 'raw_artist']
    can_delete = False
    max_num = 0
    show_change_link = False


@admin.register(WeeklyUpload)
class WeeklyUploadAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'chart_type', 'year', 'month', 'week', 'processed',
                    'entries_processed', 'duplicates_dropped', 'uploaded_at', 'process_button']
    list_filter = ['chart_type', 'year', 'month', 'processed']
    readonly_fields = ['processed', 'processing_notes', 'duplicates_dropped',
                       'entries_processed', 'uploaded_at', 'uploaded_by']
    inlines = [PlatformChartEntryInline]

    def process_button(self, obj):
        if not obj.processed:
            return format_html(
                '<a class="button" href="{}process/">Process</a>',
                obj.pk
            )
        return format_html('<span style="color:green">✓ Done ({} entries)</span>', obj.entries_processed)
    process_button.short_description = 'Action'

    def get_urls(self):
        urls = super().get_urls()
        custom = [path('<pk>/process/', self.admin_site.admin_view(self.process_view), name='charts-upload-process')]
        return custom + urls

    def process_view(self, request, pk):
        upload = WeeklyUpload.objects.get(pk=pk)
        try:
            result = process_weekly_upload(upload)
            messages.success(request, f"Processed: {result}")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect('..')

    def save_model(self, request, obj, form, change):
        obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
        if not change:  # new upload — auto-process
            try:
                result = process_weekly_upload(obj)
                messages.success(request, f"Auto-processed: {result}")
            except Exception as e:
                messages.warning(request, f"Saved but processing failed: {e}")


class MonthlyChartEntryInline(admin.TabularInline):
    model = MonthlyChartEntry
    extra = 0
    readonly_fields = ['rank', 'release', 'total_points', 'weeks_on_chart',
                       'platform_count', 'prev_rank', 'platform']
    can_delete = False
    max_num = 0


@admin.register(MonthlyChart)
class MonthlyChartAdmin(admin.ModelAdmin):
    list_display = ['label', 'chart_type', 'year', 'month', 'entry_count', 'is_published', 'rebuild_button']
    list_filter = ['chart_type', 'year', 'is_published']
    list_editable = ['is_published']

    def entry_count(self, obj):
        return obj.entries.filter(platform__isnull=True).count()
    entry_count.short_description = 'Combined Entries'

    def rebuild_button(self, obj):
        return format_html('<a class="button" href="{}rebuild/">Rebuild</a>', obj.pk)
    rebuild_button.short_description = 'Action'

    def get_urls(self):
        urls = super().get_urls()
        custom = [path('<pk>/rebuild/', self.admin_site.admin_view(self.rebuild_view), name='charts-monthly-rebuild')]
        return custom + urls

    def rebuild_view(self, request, pk):
        chart = MonthlyChart.objects.get(pk=pk)
        try:
            result = rebuild_monthly_chart(chart.chart_type, chart.year, chart.month)
            messages.success(request, f"Rebuilt: {result}")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect('..')


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'is_published', 'published_at']
    list_filter = ['category', 'is_published']
    list_editable = ['is_published']
    search_fields = ['title', 'body']
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'published_at'


@admin.register(NormalizationRule)
class NormalizationRuleAdmin(admin.ModelAdmin):
    list_display = ['rule_type', 'raw_value', 'canonical_value', 'created_at']
    list_filter = ['rule_type']
    search_fields = ['raw_value', 'canonical_value']


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ['release', 'level', 'total_points', 'certified_at']
    list_filter = ['level', 'release__chart_type']
    search_fields = ['release__title', 'release__artist__name']


@admin.register(MonthlyChartEntry)
class MonthlyChartEntryAdmin(admin.ModelAdmin):
    list_display = ['rank', 'release', 'chart', 'platform', 'total_points', 'movement']
    list_filter = ['chart__chart_type', 'chart__year', 'chart__month', 'platform']
    search_fields = ['release__title', 'release__artist__name']
    raw_id_fields = ['release', 'chart', 'platform']


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'is_active_editor', 'last_seen_at']
    list_filter = ['role', 'is_active_editor']
    search_fields = ['user__username', 'user__email']


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'region', 'active', 'display_order']
    list_editable = ['active', 'display_order']
    search_fields = ['name', 'code', 'region']


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ['key', 'group', 'updated_at', 'updated_by']
    list_filter = ['group']
    search_fields = ['key', 'description']


@admin.register(PageContent)
class PageContentAdmin(admin.ModelAdmin):
    list_display = ['page', 'section', 'title', 'is_visible', 'display_order', 'updated_at']
    list_filter = ['page', 'is_visible']
    search_fields = ['page', 'section', 'title', 'content']


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ['title', 'folder', 'uploaded_by', 'uploaded_at', 'is_archived']
    list_filter = ['folder', 'is_archived']
    search_fields = ['title', 'alt_text', 'usage_notes']


@admin.register(ChartUpload)
class ChartUploadAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'status', 'row_count', 'uploaded_by', 'approved_by', 'published_by', 'created_at']
    list_filter = ['chart_type', 'year', 'month', 'status', 'platform']
    search_fields = ['original_filename', 'notes']
    readonly_fields = ['rows_data', 'validation_summary', 'row_count', 'uploaded_by', 'approved_by', 'published_by', 'approved_at', 'published_at']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'user', 'action', 'module', 'object_repr', 'ip_address']
    list_filter = ['module', 'action', 'created_at']
    search_fields = ['action', 'module', 'object_repr', 'reason', 'user__username']
    readonly_fields = [field.name for field in AuditLog._meta.fields]


@admin.register(InternalNote)
class InternalNoteAdmin(admin.ModelAdmin):
    list_display = ['module', 'object_id', 'created_by', 'created_at', 'is_resolved']
    list_filter = ['module', 'is_resolved']
    search_fields = ['note', 'object_id']


@admin.register(AdminNotification)
class AdminNotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'level', 'module', 'user', 'is_read', 'created_at']
    list_filter = ['level', 'module', 'is_read']
    search_fields = ['title', 'message']


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ['status', 'file', 'created_by', 'created_at']
    list_filter = ['status']


@admin.register(DataQualityIssue)
class DataQualityIssueAdmin(admin.ModelAdmin):
    list_display = ['module', 'issue_type', 'severity', 'status', 'created_at']
    list_filter = ['module', 'severity', 'status']
    search_fields = ['issue_type', 'description']


@admin.register(CertificationRule)
class CertificationRuleAdmin(admin.ModelAdmin):
    list_display = ['level', 'threshold', 'active', 'updated_at']
    list_editable = ['threshold', 'active']


@admin.register(MethodologySetting)
class MethodologySettingAdmin(admin.ModelAdmin):
    list_display = ['version', 'name', 'is_active', 'created_at', 'created_by']
    list_filter = ['is_active']
    search_fields = ['version', 'name']


@admin.register(ArtistMergeLog)
class ArtistMergeLogAdmin(admin.ModelAdmin):
    list_display = ['primary_artist', 'merged_artist_name', 'moved_releases', 'merged_by', 'created_at']
    search_fields = ['primary_artist__name', 'merged_artist_name']


@admin.register(PlaceholderModule)
class PlaceholderModuleAdmin(admin.ModelAdmin):
    list_display = ['module', 'title', 'status', 'updated_at']
    list_filter = ['module', 'status']
    search_fields = ['module', 'title']
