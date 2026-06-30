from rest_framework.permissions import BasePermission, SAFE_METHODS
from .models import AdminRole, AdminProfile

ROLE_ORDER = {
    AdminRole.VIEWER: 0,
    AdminRole.NEWS_EDITOR: 1,
    AdminRole.DATA_EDITOR: 1,
    AdminRole.EDITOR: 2,
    AdminRole.REVIEWER: 3,
    AdminRole.ADMIN: 4,
    AdminRole.SUPER_ADMIN: 5,
}

PUBLISH_ROLES = {AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.REVIEWER}
ADMIN_ROLES = {AdminRole.SUPER_ADMIN, AdminRole.ADMIN}
NEWS_ROLES = {AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.EDITOR, AdminRole.NEWS_EDITOR, AdminRole.REVIEWER}
DATA_ROLES = {AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.EDITOR, AdminRole.DATA_EDITOR, AdminRole.REVIEWER}

NEWS_MODULES = {'news'}
DATA_MODULES = {
    'artists', 'releases', 'countries', 'platforms', 'charts', 'chart_entries',
    'chart_uploads', 'uploads', 'certifications', 'certification_rules',
    'methodology', 'reports',
}
EDITORIAL_MODULES = {'media', 'page_content', 'notes', 'notifications'}
ADMIN_MODULES = {'users', 'settings', 'backups', 'future_modules'}

# These actions alter public state, historical data, or access control and must
# never be available merely because a user can edit ordinary records.
PUBLISH_ACTIONS = {
    'publish', 'unpublish', 'approve', 'reject', 'rollback', 'recalculate',
    'bulk_publish', 'lock', 'unlock',
}
ADMIN_ACTIONS = {
    'destroy', 'hard_delete', 'create_user', 'set_role',
}


def _module_name(view):
    return getattr(view, 'module_name', '') or ''


def get_user_role(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return AdminRole.SUPER_ADMIN
    profile, _ = AdminProfile.objects.get_or_create(user=user)
    return profile.role


class IsCmsUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and get_user_role(request.user))


class CmsRolePermission(BasePermission):
    """Role and module-aware CMS permission policy.

    Viewers are read-only. Specialist editors can only mutate their own
    modules, reviewers can publish, and destructive operations remain admin
    only. The backend is authoritative; hiding a button in React is not a
    security boundary.
    """
    def has_permission(self, request, view):
        role = get_user_role(request.user)
        if not role:
            return False
        if request.method in SAFE_METHODS:
            return True
        action = getattr(view, 'action', '')
        if action in PUBLISH_ACTIONS:
            return role in PUBLISH_ROLES
        if action in ADMIN_ACTIONS:
            return role in ADMIN_ROLES
        module = _module_name(view)
        if module in ADMIN_MODULES:
            return role in ADMIN_ROLES
        if module in NEWS_MODULES:
            return role in NEWS_ROLES
        if module in DATA_MODULES:
            return role in DATA_ROLES
        if module in EDITORIAL_MODULES:
            return role in (NEWS_ROLES | DATA_ROLES)
        return role in {AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.EDITOR, AdminRole.REVIEWER}


class CmsAdminOnly(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) in ADMIN_ROLES


class CmsPublishPermission(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) in PUBLISH_ROLES
