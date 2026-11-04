from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


TARIFF_ADMIN_GROUP = "Administración CINTAC"
USER_MANAGER_USERNAME = "SuperAdminCintac"


def is_tariff_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=TARIFF_ADMIN_GROUP).exists()
    )


def can_view_all_quotes(user):
    return is_tariff_admin(user)


def is_user_manager(user):
    return (
        user.is_authenticated
        and user.get_username() == USER_MANAGER_USERNAME
        and is_tariff_admin(user)
    )


def tariff_admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_tariff_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def user_manager_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_user_manager(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped
