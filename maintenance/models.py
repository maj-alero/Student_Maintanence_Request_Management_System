from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    ROLE_CHOICES = (
        ('Student', 'Student'),
        ('Staff', 'Staff'),
        ('Admin', 'Admin'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='Student')

    def __str__(self):
        return f"{self.username} ({self.role})"


class MaintenanceRequest(models.Model):
    CATEGORY_CHOICES = (
        ('Plumbing', 'Plumbing'),
        ('Electrical', 'Electrical'),
        ('Carpentry', 'Carpentry'),
    )

    LOCATION_CHOICES = (
        ('Bathroom', 'Bathroom'),
        ('Room', 'Room'),
        ('Corridor', 'Corridor'),
    )

    WING_CHOICES = [(c, f'Wing {c}') for c in 'ABCDEFGH']

    URGENCY_CHOICES = [(i, str(i)) for i in range(1, 6)]

    IMPACT_CHOICES = (
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    )

    RECURRENCE_CHOICES = (
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Unsure', 'Unsure'),
    )

    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('In Progress', 'In Progress'),
        ('Resolved', 'Resolved'),
    )
    HOSTEL_CHOICES = (
        ('Lydia Hall','Lydia Hall'),
        ('Deborah Hall','Deborah Hall'),
        ('Mary Hall','Mary Hall'),
        ('Dorcas Hall', 'Dorcas Hall'),
        ('Daniel Hall','Daniel Hall'),
        ('Joseph Hall','Joseph Hall'),
        ('Paul Hall','Paul Hall'),
        ('Peter Hall', 'Peter Hall'),
        ('John Hall','John Hall'),
        ('Joshua Hall','Joshua Hall'),
    )
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    location = models.CharField(max_length=100, choices=LOCATION_CHOICES)
    hostel_name = models.CharField(max_length=100, choices=HOSTEL_CHOICES)
    wing = models.CharField(max_length=1, choices=WING_CHOICES, default='A')
    room_number = models.CharField(max_length=10, default='')
    description = models.TextField()
    photo = models.ImageField(upload_to='request_photos/', blank=True, null=True)
    urgency_level = models.IntegerField(choices=URGENCY_CHOICES)
    affected_users = models.IntegerField(default=1)
    time_sensitivity = models.BooleanField(default=False)
    impact_level = models.CharField(max_length=10, choices=IMPACT_CHOICES)
    recurrence = models.CharField(max_length=10, choices=RECURRENCE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    resolved_at = models.DateTimeField(null=True, blank=True)

    submitted_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='submitted_requests'
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    @property
    def resolution_time(self):
        if self.resolved_at and self.timestamp:
            delta = self.resolved_at - self.timestamp
            total_seconds = int(delta.total_seconds())
            days = delta.days
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            if days > 0:
                return f"{days}d {hours}h"
            elif hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        return None

    def __str__(self):
        return f"{self.category} at {self.hostel_name} Wing {self.wing} Rm {self.room_number} — {self.status}"


class PriorityClassification(models.Model):
    PRIORITY_CHOICES = (
        ('High', 'High'),
        ('Medium', 'Medium'),
        ('Low', 'Low'),
    )
    request = models.OneToOneField(
        MaintenanceRequest, on_delete=models.CASCADE, related_name='priority'
    )
    priority_label = models.CharField(max_length=10, choices=PRIORITY_CHOICES)
    classified_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Priority: {self.priority_label} for Request #{self.request.id}"


class Assignment(models.Model):
    request = models.ForeignKey(
        MaintenanceRequest, on_delete=models.CASCADE, related_name='assignments'
    )
    assigned_to = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='assignments'
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='assigned_tasks'
    )
    notes = models.TextField(blank=True, null=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Request #{self.request.id} assigned to {self.assigned_to.username}"


class StatusHistory(models.Model):
    request = models.ForeignKey(
        MaintenanceRequest, on_delete=models.CASCADE, related_name='status_history'
    )
    previous_status = models.CharField(
        max_length=20, choices=MaintenanceRequest.STATUS_CHOICES, blank=True, null=True
    )
    new_status = models.CharField(
        max_length=20, choices=MaintenanceRequest.STATUS_CHOICES
    )
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='status_changes'
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Request #{self.request.id}: {self.previous_status} → {self.new_status}"



class Notification(models.Model):
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications'
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notif → {self.recipient.username}: {self.message[:40]}"
