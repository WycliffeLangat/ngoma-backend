from django.contrib.auth.models import User
from rest_framework import serializers
from django.db import transaction
from django.db.models import Min, Q, Sum

from .models import *
from .artist_credits import release_credit_payload
from .cms_utils import published_artist_entries, published_top50_entries

ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/svg+xml'}


def validate_upload(file_value, max_megabytes, allowed_types=None, label='file'):
    if not file_value:
        return file_value
    max_bytes = max_megabytes * 1024 * 1024
    if getattr(file_value, 'size', 0) > max_bytes:
        raise serializers.ValidationError(f'The {label} must be {max_megabytes} MB or smaller.')
    content_type = (getattr(file_value, 'content_type', '') or '').lower()
    if allowed_types and content_type and content_type not in allowed_types:
        readable = ', '.join(sorted(item.split('/')[-1].upper() for item in allowed_types))
        raise serializers.ValidationError(f'Unsupported {label} type. Use one of: {readable}.')
    return file_value


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
    total_releases = serializers.SerializerMethodField()
    total_points = serializers.SerializerMethodField()
    peak_rank = serializers.SerializerMethodField()
    months_on_chart = serializers.SerializerMethodField()
    entry_count = serializers.SerializerMethodField()
    missing_country = serializers.SerializerMethodField()
    flag = serializers.ReadOnlyField()
    image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Artist
        fields = '__all__'

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        request = self.context.get('request')
        if request and rep.get('image') and not str(rep['image']).startswith('http'):
            rep['image'] = request.build_absolute_uri(rep['image'])
        return rep

    def get_total_releases(self, obj):
        annotated = getattr(obj, 'cms_total_releases', None)
        if annotated is not None:
            return annotated
        return Release.objects.filter(
            Q(artist=obj) | Q(artist_credits__artist=obj)
        ).distinct().count()

    def get_total_points(self, obj):
        annotated = getattr(obj, 'cms_total_points', None)
        if annotated is not None:
            return annotated
        return published_artist_entries(obj).aggregate(total=Sum('total_points'))['total'] or 0

    def get_peak_rank(self, obj):
        if hasattr(obj, 'cms_peak_rank'):
            return obj.cms_peak_rank
        return published_artist_entries(obj).aggregate(p=Min('rank'))['p']

    def get_months_on_chart(self, obj):
        if hasattr(obj, 'cms_months_on_chart'):
            return obj.cms_months_on_chart
        return published_artist_entries(obj).values('chart').distinct().count()

    def get_entry_count(self, obj):
        if hasattr(obj, 'cms_entry_count'):
            return obj.cms_entry_count
        return published_artist_entries(obj).count()

    def get_missing_country(self, obj):
        return not bool(obj.country or obj.country_code)

    def validate_image(self, value):
        return validate_upload(value, 2, ALLOWED_IMAGE_TYPES - {'image/svg+xml'}, 'artist image')

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
    artist = serializers.PrimaryKeyRelatedField(queryset=Artist.objects.all(), required=False)
    artist_name = serializers.CharField(source='artist.name', read_only=True)
    artist_display = serializers.SerializerMethodField()
    primary_artist_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
    featured_artist_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
    cover_image = serializers.ImageField(required=False, allow_null=True)
    primary_artists = serializers.SerializerMethodField()
    featured_artist_profiles = serializers.SerializerMethodField()
    artist_credit = serializers.SerializerMethodField()
    total_points = serializers.SerializerMethodField()
    peak_rank = serializers.SerializerMethodField()
    months_on_chart = serializers.SerializerMethodField()
    entry_count = serializers.SerializerMethodField()
    certifications = serializers.SerializerMethodField()

    class Meta:
        model = Release
        fields = '__all__'

    def get_artist_display(self, obj):
        return release_credit_payload(obj)['primary_artist_credit']

    @staticmethod
    def _artist_summary(artist):
        return {
            'id': artist.id,
            'name': artist.name,
            'display_name': artist.display_name,
            'public_name': artist.display_name or artist.name,
            'slug': artist.slug,
            'country': artist.country,
            'country_code': artist.country_code,
        }

    def get_primary_artists(self, obj):
        return [self._artist_summary(artist) for artist in release_credit_payload(obj)['primary_artists']]

    def get_featured_artist_profiles(self, obj):
        return [self._artist_summary(artist) for artist in release_credit_payload(obj)['featured_artists']]

    def get_artist_credit(self, obj):
        return release_credit_payload(obj)['artist_credit']

    def get_total_points(self, obj):
        annotated = getattr(obj, 'cms_total_points', None)
        if annotated is not None:
            return annotated
        return published_top50_entries().filter(release=obj).aggregate(total=Sum('total_points'))['total'] or 0

    def get_peak_rank(self, obj):
        if hasattr(obj, 'cms_peak_rank'):
            return obj.cms_peak_rank
        return published_top50_entries().filter(release=obj).aggregate(peak=Min('rank'))['peak']

    def get_months_on_chart(self, obj):
        if hasattr(obj, 'cms_months_on_chart'):
            return obj.cms_months_on_chart
        return published_top50_entries().filter(release=obj).values('chart').distinct().count()

    def get_entry_count(self, obj):
        if hasattr(obj, 'cms_entry_count'):
            return obj.cms_entry_count
        return published_top50_entries().filter(release=obj).count()

    def get_certifications(self, obj):
        return [
            {'level': item.level, 'total_points': item.total_points, 'certified_at': item.certified_at, 'is_official': item.is_official}
            for item in obj.certifications.all()
        ]

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        request = self.context.get('request')
        if request and rep.get('cover_image') and not str(rep['cover_image']).startswith('http'):
            rep['cover_image'] = request.build_absolute_uri(rep['cover_image'])
        return rep

    def validate_cover_image(self, value):
        return validate_upload(value, 2, ALLOWED_IMAGE_TYPES - {'image/svg+xml'}, 'cover image')

    def validate(self, attrs):
        primary_ids = list(dict.fromkeys(attrs.get('primary_artist_ids', [])))
        featured_ids = list(dict.fromkeys(attrs.get('featured_artist_ids', [])))
        if 'primary_artist_ids' not in attrs and attrs.get('artist') and self.instance is not None:
            existing_ids = [artist_id for artist_id in self.instance.primary_artist_ids if artist_id != attrs['artist'].id]
            primary_ids = [attrs['artist'].id, *existing_ids]
            attrs['primary_artist_ids'] = primary_ids
        if 'primary_artist_ids' in attrs:
            if not primary_ids:
                raise serializers.ValidationError({'primary_artist_ids': 'Choose at least one main artist.'})
            found_ids = set(Artist.objects.filter(id__in=primary_ids).values_list('id', flat=True))
            missing_ids = [artist_id for artist_id in primary_ids if artist_id not in found_ids]
            if missing_ids:
                raise serializers.ValidationError({'primary_artist_ids': f'Unknown artist ID(s): {missing_ids}'})
            attrs['primary_artist_ids'] = primary_ids
            attrs['artist'] = Artist.objects.get(pk=primary_ids[0])
        elif self.instance is None and not attrs.get('artist'):
            raise serializers.ValidationError({'artist': 'Choose at least one main artist.'})

        if 'featured_artist_ids' in attrs:
            found_ids = set(Artist.objects.filter(id__in=featured_ids).values_list('id', flat=True))
            missing_ids = [artist_id for artist_id in featured_ids if artist_id not in found_ids]
            if missing_ids:
                raise serializers.ValidationError({'featured_artist_ids': f'Unknown artist ID(s): {missing_ids}'})
            attrs['featured_artist_ids'] = featured_ids

        effective_primary_ids = primary_ids if 'primary_artist_ids' in attrs else (
            self.instance.primary_artist_ids if self.instance else [attrs['artist'].id]
        )
        effective_featured_ids = featured_ids if 'featured_artist_ids' in attrs else (
            self.instance.featured_artist_ids if self.instance else []
        )
        overlap = sorted(set(effective_primary_ids) & set(effective_featured_ids))
        if overlap:
            raise serializers.ValidationError({'featured_artist_ids': 'An artist cannot be both a main and featured artist on the same release.'})

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

    @transaction.atomic
    def create(self, validated_data):
        primary_ids = validated_data.pop('primary_artist_ids', None)
        featured_ids = validated_data.pop('featured_artist_ids', None)
        instance = super().create(validated_data)
        self._sync_artist_credits(instance, primary_ids, featured_ids)
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        primary_ids = validated_data.pop('primary_artist_ids', None)
        featured_ids = validated_data.pop('featured_artist_ids', None)
        instance = super().update(instance, validated_data)
        self._sync_artist_credits(instance, primary_ids, featured_ids)
        return instance

    def _sync_artist_credits(self, instance, primary_ids, featured_ids):
        if primary_ids is None and not instance.artist_credits.filter(role='primary').exists():
            primary_ids = [instance.artist_id]
        if primary_ids is not None:
            instance.artist_credits.filter(role='primary').delete()
            ReleaseArtistCredit.objects.bulk_create([
                ReleaseArtistCredit(release=instance, artist_id=artist_id, role='primary', position=position)
                for position, artist_id in enumerate(primary_ids)
            ])
            if instance.artist_id != primary_ids[0]:
                instance.artist_id = primary_ids[0]
                instance.save(update_fields=['artist', 'updated_at'])
        if featured_ids is not None:
            instance.artist_credits.filter(role='featured').delete()
            ReleaseArtistCredit.objects.bulk_create([
                ReleaseArtistCredit(release=instance, artist_id=artist_id, role='featured', position=position)
                for position, artist_id in enumerate(featured_ids)
            ])
            names = [
                artist.display_name or artist.name
                for artist in sorted(Artist.objects.filter(id__in=featured_ids), key=lambda artist: featured_ids.index(artist.id))
            ]
            instance.featured_artists = ', '.join(names)
            instance.save(update_fields=['featured_artists', 'updated_at'])
        instance._prefetched_objects_cache = {}


class CmsMonthlyChartEntrySerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='release.title', read_only=True)
    artist = serializers.CharField(source='release.artist.name', read_only=True)
    artist_display = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    platform_name = serializers.SerializerMethodField()
    movement = serializers.ReadOnlyField()

    class Meta:
        model = MonthlyChartEntry
        fields = '__all__'

    def get_platform_name(self, obj):
        return obj.platform.name if obj.platform else 'Combined'

    def get_artist_display(self, obj):
        return release_credit_payload(
            obj.release,
            entry_featured=obj.featured_artists,
        )['artist_credit']

    def get_cover_image(self, obj):
        if not obj.release_id:
            return None
        img = obj.release.cover_image
        if not img:
            return None
        request = self.context.get('request')
        url = img.url
        if request and not url.startswith('http'):
            return request.build_absolute_uri(url)
        return url


class CmsRegionalChartEntrySerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='release.title', read_only=True)
    artist = serializers.CharField(source='release.artist.name', read_only=True)
    artist_display = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    platform_name = serializers.SerializerMethodField()
    movement = serializers.ReadOnlyField()

    class Meta:
        model = RegionalChartEntry
        fields = '__all__'

    def get_platform_name(self, obj):
        return obj.region

    def get_artist_display(self, obj):
        return release_credit_payload(
            obj.release,
            entry_featured=obj.featured_artists,
        )['artist_credit']

    def get_cover_image(self, obj):
        if not obj.release_id:
            return None
        img = obj.release.cover_image
        if not img:
            return None
        request = self.context.get('request')
        url = img.url
        if request and not url.startswith('http'):
            return request.build_absolute_uri(url)
        return url


class CmsMonthlyChartSerializer(serializers.ModelSerializer):
    entries_count = serializers.SerializerMethodField()
    combined_entries_count = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyChart
        fields = '__all__'

    def validate(self, attrs):
        year = attrs.get('year', getattr(self.instance, 'year', None))
        month = attrs.get('month', getattr(self.instance, 'month', None))
        status_value = attrs.get('status', getattr(self.instance, 'status', 'draft'))
        is_published = attrs.get('is_published', getattr(self.instance, 'is_published', False))

        if year is not None and not 1900 <= year <= 2200:
            raise serializers.ValidationError({'year': 'Enter a year between 1900 and 2200.'})
        if month is not None and not 1 <= month <= 12:
            raise serializers.ValidationError({'month': 'Enter a month from 1 to 12.'})
        if is_published and status_value != 'published':
            raise serializers.ValidationError({
                'status': 'A public chart must have Published status. Use the Publish action when review is complete.'
            })
        if status_value == 'published' and not is_published:
            raise serializers.ValidationError({
                'is_published': 'Published status requires the chart to be public.'
            })

        if self.instance and self.instance.locked:
            protected = {'year', 'month', 'chart_type', 'status', 'is_published'}
            changed = [
                field for field in protected
                if field in attrs and attrs[field] != getattr(self.instance, field)
            ]
            if changed:
                raise serializers.ValidationError({
                    'detail': 'This published chart is locked. Unlock it before changing its period or publication state.'
                })
        return attrs

    def get_entries_count(self, obj):
        annotated = getattr(obj, 'cms_entries_count', None)
        if annotated is not None:
            return annotated
        return obj.entries.count()

    def get_combined_entries_count(self, obj):
        annotated = getattr(obj, 'cms_combined_entries_count', None)
        if annotated is not None:
            return annotated
        return obj.entries.filter(platform__isnull=True).count()


class CmsNewsArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsArticle
        fields = '__all__'

    def validate_cover_image(self, value):
        return validate_upload(value, 5, ALLOWED_IMAGE_TYPES - {'image/svg+xml'}, 'news image')


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

    def validate_file(self, value):
        return validate_upload(value, 5, ALLOWED_IMAGE_TYPES, 'media file')


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

    def validate_file(self, value):
        validated = validate_upload(
            value, 20,
            {'text/csv', 'application/csv', 'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
            'chart file',
        )
        extension = str(getattr(value, 'name', '')).lower().rsplit('.', 1)[-1]
        if extension not in {'csv', 'xlsx', 'xlsm'}:
            raise serializers.ValidationError('Chart files must be CSV, XLSX or XLSM.')
        return validated


class CmsWeeklyUploadSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=True)
    original_filename = serializers.SerializerMethodField()

    class Meta:
        model = WeeklyUpload
        fields = [
            'id', 'chart_type', 'year', 'month', 'week', 'file',
            'original_filename', 'processed', 'processing_notes',
            'duplicates_dropped', 'entries_processed', 'uploaded_at',
        ]
        read_only_fields = [
            'original_filename', 'processed', 'processing_notes',
            'duplicates_dropped', 'entries_processed', 'uploaded_at',
        ]

    def get_original_filename(self, obj):
        name = str(getattr(obj.file, 'name', '') or '')
        return name.replace('\\', '/').rsplit('/', 1)[-1]

    def validate_file(self, value):
        validated = validate_upload(value, 20, label='weekly chart file')
        extension = str(getattr(value, 'name', '')).lower().rsplit('.', 1)[-1]
        if extension not in {'xlsx', 'xlsm'}:
            raise serializers.ValidationError('Raw weekly chart files must be XLSX or XLSM.')
        return validated


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
