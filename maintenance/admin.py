from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, MaintenanceRequest, PriorityClassification, Assignment, StatusHistory

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role Information', {'fields': ('role',)}),
    )
    list_display = ['username', 'email', 'role', 'is_staff']

admin.site.register(User, CustomUserAdmin)
admin.site.register(MaintenanceRequest)
admin.site.register(PriorityClassification)
admin.site.register(Assignment)
admin.site.register(StatusHistory)
