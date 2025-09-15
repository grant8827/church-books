from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

class Command(BaseCommand):
    help = 'Ensure a superuser account exists'

    def handle(self, *args, **options):
        if not User.objects.filter(is_superuser=True).exists():
            admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
            admin_email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
            
            User.objects.create_superuser(
                username=admin_username,
                email=admin_email,
                password=admin_password
            )
            self.stdout.write(
                self.style.SUCCESS(f'Superuser "{admin_username}" created successfully!')
            )
        else:
            self.stdout.write(
                self.style.WARNING('Superuser already exists.')
            )