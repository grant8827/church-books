"""
Management command to wait for database connection to be ready.
This helps ensure database is ready before starting the main application.
"""

from django.core.management.base import BaseCommand
from django.db import connections, connection
from django.db.utils import OperationalError
import time
import sys


class Command(BaseCommand):
    help = 'Wait for database to be available'

    def add_arguments(self, parser):
        parser.add_argument(
            '--timeout',
            type=int,
            default=60,
            help='Maximum time to wait for database (seconds)',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=2,
            help='Time between connection attempts (seconds)',
        )

    def handle(self, *args, **options):
        timeout = options['timeout']
        interval = options['interval']
        
        start_time = time.time()
        
        self.stdout.write('Waiting for database connection...')
        
        while True:
            try:
                # Try to connect to the default database
                connection.ensure_connection()
                
                # Try a simple query
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                
                self.stdout.write(
                    self.style.SUCCESS('Database connection is ready!')
                )
                return
                
            except OperationalError as e:
                elapsed = time.time() - start_time
                
                if elapsed >= timeout:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Database connection failed after {timeout} seconds. '
                            f'Last error: {e}'
                        )
                    )
                    sys.exit(1)
                
                self.stdout.write(
                    f'Database not ready (attempt {int(elapsed/interval)+1}): {e}'
                )
                time.sleep(interval)
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Unexpected error: {e}')
                )
                sys.exit(1)