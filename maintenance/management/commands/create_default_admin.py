# maintenance/management/commands/create_default_admin.py

from django.core.management.base import BaseCommand
from maintenance.models import User

class Command(BaseCommand):
    help = 'Creates a default admin user if none exists'

    def handle(self, *args, **kwargs):
        if not User.objects.filter(role='Admin').exists():
            User.objects.create_superuser(
                username='admin',
                email='admin@fixit.com',
                password='Admin1234!',
                role='Admin'
            )
            self.stdout.write('Default admin created successfully.')
        else:
            self.stdout.write('Admin already exists. Skipping.')