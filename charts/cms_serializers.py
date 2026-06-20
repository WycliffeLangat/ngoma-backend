from django.contrib.auth.models import User
from rest_framework import serializers
from .models import *


class AdminProfileSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = AdminProfile
        fields = ['role', 'role_label', 'phone', 'avatar', 'is_active_editor', 'last_seen_at']


class CmsUserSerializer(serializers.ModelSerializer):
    profile = AdminProfileSerializer(source='cms_profile', read_only=True)
    role = serializers.CharField(write_only=True, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'is_superuser', 'last_login', 'date_joined', 'profile', 'role', 'password']
        read_only_fields = ['is_superuser', 'last_login', 'date_joined']

    def create(self, validated_data):
        role = validated_data.pop('role', AdminRole.VIEWER)
        password = validated_data.pop('password', None) or User.objects.make_random_password()
        user = User(**validated_data)
        user.set_password(password)
        user.is_staff = True
        user.save()
        AdminProfile.objects.update_or_create(user=user, defaults={'role': role})
        return user

    def update(self, instance, validated_data):
        role = validated_data.pop('role', None)
        password = validated_data.pop('password', None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        if role:
            AdminProfile.objects.update_or_create(user=instance, defaults={'role': role})
        return instance


class CmsMeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'role', 'role_label', 'permissions']

    def get_role(self, obj):
        if obj.is_superuser:
            return AdminRole.SUPER_ADMIN
        profile, _ = AdminProfile.objects.get_or_create(user=obj)
        return profile.role

    def get_role_label(self, obj):
        if obj.is_superuser:
            return 'Super Admin'
        profile, _ = AdminProfile.objects.get_or_create(user=obj)
        return profile.get_role_display()

    def get_permissions(self, obj):
        role = self.get_role(obj)
        return {
            'can_publish': role in {AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.REVIEWER},
            'can_manage_users': role in {AdminRole.SUPER_ADMIN, AdminRole.ADMIN},
            'can_manage_data': role in {AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.EDITOR, AdminRole.DATA_EDITOR, AdminRole.REVIEWER},
            'can_manage_news': role in {AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.EDITOR, AdminRole.NEWS_EDITOR, AdminRole.REVIEWER},
            'read_only': role == AdminRole.VIEWER,
        }


class CmsPlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = '__all__'


class CmsCountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = '__all__'


class CmsArtistSerializer(serializers.ModelSerializer):
    total_releases = serializers.IntegerField(source='releases.count', read_only=True)
    total_points = serializers.SerializerMethodField()
    missing_country = serializers.SerializerMethodField()
    flag = serializers.ReadOnlyField()

    class Meta:
        model = Artist
        fields = '__all__'

    def get_total_points(self, obj):
        from django.db.models import Sum
        return MonthlyChartEntry.objects.filter(release__artist=obj).aggregate(total=Sum('total_points'))['total'] or 0

    def get_missing_country(self, obj):
        return not bool(obj.country or obj.country_code)

    def validate(self, attrs):
        incoming_country = attrs.get('country')
        incoming_code = attrs.get('country_code')

        # Country name changed but code not included in this request → auto-derive it.
        if incoming_country and incoming_code is None:
            code = (
                Country.objects.filter(name__iexact=incoming_country.strip(), active=True)
                .values_list('code', flat=True)
                .first()
            ) or (
                Artist.objects.filter(country__iexact=incoming_country.strip())
                .exclude(country_code='')
                .values_list('country_code', flat=True)
                .first()
            )
            if code:
                attrs['country_code'] = code.upper()

        # Country code changed but name not included in this request → auto-derive it.
        elif incoming_code and incoming_country is None:
            name = (
                Country.objects.filter(code__iexact=incoming_code.strip(), active=True)
                .values_list('name', flat=True)
                .first()
            ) or (
                Artist.objects.filter(country_code__iexact=incoming_code.strip())
                .exclude(country='')
                .values_list('country', flat=True)
                .first()
            )
            if name:
                attrs['country'] = name

        return attrs


class CmsReleaseSerializer(serializers.ModelSerializer):
    artist_name = serializers.CharField(source='artist.name', read_only=True)
    artist_display = serializers.SerializerMethodField()
    total_points = serializers.SerializerMethodField()
    peak_rank = serializers.SerializerMethodField()
    months_on_chart = serializers.SerializerMethodField()
    certifications = serializers.SerializerMethodField()

    class Meta:
        model = Release
        fields = '__all__'

    def get_artist_display(self, obj):
        return obj.artist.display_name or obj.artist.name

    def get_total_points(self, obj):
        from django.db.models import Sum
        return MonthlyChartEntry.objects.filter(release=obj, platform__isnull=True).aggregate(total=Sum('total_points'))['total'] or 0

    def get_peak_rank(self, obj):
        from django.db.models import Min
        return MonthlyChartEntry.objects.filter(release=obj, platform__isnull=True).aggregate(peak=Min('rank'))['peak']

    def get_months_on_chart(self, obj):
        return MonthlyChartEntry.objects.filter(release=obj, platform__isnull=True).values('chart').distinct().count()

    def get_certifications(self, obj):
        return list(obj.certifications.values('level', 'total_points', 'certified_at', 'is_official'))

    def validate(self, attrs):
        incoming_country = attrs.get('country')
        incoming_code = attrs.get('country_code')

        if incoming_country and incoming_code is None:
            code = (
                Country.objects.filter(name__iexact=incoming_country.strip(), active=True)
                .values_list('code', flat=True)
                .first()
            ) or (
                Release.objects.filter(country__iexact=incoming_country.strip())
                .exclude(country_code='')
                .values_list('country_code', flat=True)
                .first()
            )
            if code:
                attrs['country_code'] = code.upper()

        elif incoming_code and incoming_country is None:
            name = (
                Country.objects.filter(code__iexact=incoming_code.strip(), active=True)
                .values_list('name', flat=True)
                .first()
            ) or (
                Release.objects.filter(country_code__iexact=incoming_code.strip())
                .exclude(country='')
                .values_list('country', flat=True)
                .first()
            )
            if name:
                attrs['country'] = name

        return attrs


class CmsMonthlyChartEntrySerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='release.title', read_only=True)
    artist = serializers.CharField(source='release.artist.name', read_only=True)
    platform_name = serializers.SerializerMethodField()
    movement = serializers.ReadOnlyField()

    class Meta:
        model = MonthlyChartEntry
        fields = '__all__'

    def get_platform_name(self, obj):
        return obj.platform.name if obj.platform else 'Combined'


class CmsMonthlyChartSerializer(serializers.ModelSerializer):
    entries_count = serializers.SerializerMethodField()
    combined_entries_count = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyChart
        fields = '__all__'

    def get_entries_count(self, obj):
        return obj.entries.count()

    def get_combined_entries_count(self, obj):
        return obj.entries.filter(platform__isnull=True).count()


class CmsNewsArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsArticle
        fields = '__all__'


class CmsCertificationSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='release.title', read_only=True)
    artist = serializers.CharField(source='release.artist.name', read_only=True)

    class Meta:
        model = Certification
        fields = '__all__'


class CertificationRuleSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source='get_level_display', read_only=True)

    class Meta:
        model = CertificationRule
        fields = '__all__'


class MethodologySettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MethodologySetting
        fields = '__all__'


class SiteSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSetting
        fields = '__all__'


class PageContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PageContent
        fields = '__all__'


class MediaAssetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = MediaAsset
        fields = '__all__'

    def get_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        if obj.file:
            return obj.file.url
        return ''


class ChartUploadSerializer(serializers.ModelSerializer):
    platform_name = serializers.CharField(source='platform.name', read_only=True)
    uploaded_by_name = serializers.CharField(source='uploaded_by.username', read_only=True)
    can_publish = serializers.SerializerMethodField()

    class Meta:
        model = ChartUpload
        fields = '__all__'
        read_only_fields = ['rows_data', 'validation_summary', 'row_count', 'uploaded_by', 'approved_by', 'published_by', 'approved_at', 'published_at', 'original_filename']

    def get_can_publish(self, obj):
        return bool(obj.validation_summary.get('can_publish')) if obj.validation_summary else False


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'


class InternalNoteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = InternalNote
        fields = '__all__'
        read_only_fields = ['created_by']


class AdminNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminNotification
        fields = '__all__'


class BackupRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupRecord
        fields = '__all__'


class DataQualityIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataQualityIssue
        fields = '__all__'


class PlaceholderModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlaceholderModule
        fields = '__all__'
