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
    """General CMS permission: viewers can read; editors/admins can write."""
    def has_permission(self, request, view):
        role = get_user_role(request.user)
        if not role:
            return False
        if request.method in SAFE_METHODS:
            return True
        action = getattr(view, 'action', '')
        if action in {'publish', 'approve', 'reject', 'rollback', 'recalculate', 'bulk_publish'}:
            return role in PUBLISH_ROLES
        if action in {'destroy', 'create_user', 'set_role'}:
            return role in ADMIN_ROLES
        return ROLE_ORDER.get(role, 0) >= 1


class CmsAdminOnly(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) in ADMIN_ROLES


class CmsPublishPermission(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) in PUBLISH_ROLES
