"""
maintenance/context_processors.py

Registered in settings.py under TEMPLATES > OPTIONS > context_processors.
Injects `unread_count` into every template automatically so base.html
can show the notification bell badge without each view passing it manually.
"""


def unread_notifications(request):
    if request.user.is_authenticated:
        from maintenance.models import Notification
        count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()
        return {'unread_count': count}
    return {'unread_count': 0}
