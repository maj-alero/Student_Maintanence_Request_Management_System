from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied

def student_required(view_func):
    def check_is_student(user):
        if user.is_authenticated and user.role == 'Student':
            return True
        raise PermissionDenied
    return user_passes_test(check_is_student)(view_func)

def staff_required(view_func):
    def check_is_staff(user):
        if user.is_authenticated and user.role == 'Staff':
            return True
        raise PermissionDenied
    return user_passes_test(check_is_staff)(view_func)

def staff_or_admin_required(view_func):
    def check(user):
        if user.is_authenticated and (user.role in ('Staff', 'Admin') or user.is_superuser):
            return True
        raise PermissionDenied
    return user_passes_test(check)(view_func)

def admin_required(view_func):
    def check_is_admin(user):
        if user.is_authenticated and (user.role == 'Admin' or user.is_superuser):
            return True
        raise PermissionDenied
    return user_passes_test(check_is_admin)(view_func)
