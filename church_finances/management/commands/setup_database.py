from django.core.management.base import BaseCommand
from django.db import connection
from django.contrib.auth.models import User
import os

class Command(BaseCommand):
    help = 'Setup database with default user and superuser'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='admin',
            help='Username for the superuser (default: admin)'
        )
        parser.add_argument(
            '--email',
            type=str,
            default='admin@example.com',
            help='Email for the superuser (default: admin@example.com)'
        )
        parser.add_argument(
            '--password',
            type=str,
            default='admin123',
            help='Password for the superuser (default: admin123)'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up database...'))
        
        # Run migrations first
        self.stdout.write('Running migrations...')
        from django.core.management import call_command
        call_command('migrate', verbosity=0)
        
        # Create superuser if it doesn't exist
        username = options['username']
        email = options['email']
        password = options['password']
        
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username, email, password)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created superuser: {username}')
            )
        else:
            self.stdout.write(
                self.style.WARNING(f'Superuser {username} already exists')
            )
        
        # Test database connection
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version();")
                version = cursor.fetchone()
                self.stdout.write(
                    self.style.SUCCESS(f'Database connection successful: {version[0]}')
                )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Database connection failed: {e}')
            )
            return
        
        # Create a test query to verify tables
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name LIKE 'church_finances_%';
                """)
                tables = cursor.fetchall()
                if tables:
                    self.stdout.write(
                        self.style.SUCCESS(f'Found {len(tables)} church_finances tables')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('No church_finances tables found - run migrations')
                    )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Could not check tables: {e}')
            )
        
        self.stdout.write(
            self.style.SUCCESS('Database setup complete!')
        )
        self.stdout.write(f'Admin URL: http://localhost:8000/admin/')
        self.stdout.write(f'Username: {username}')
        self.stdout.write(f'Password: {password}')