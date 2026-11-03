from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def role_required(*allowed_roles):
    """Allow the view only for users whose role is in allowed_roles.

    Not logged in  -> redirect to the login page.
    Wrong role     -> 403 Forbidden.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.role not in allowed_roles:
                raise PermissionDenied(
                    f"Access Denied: Role '{request.user.role}' "
                    f"lacks permissions."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
