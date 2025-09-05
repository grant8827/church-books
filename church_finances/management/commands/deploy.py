from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Collect static files and run migrations for deployment'

    def handle(self, *args, **options):
        self.stdout.write('Collecting static files...')
        call_command('collectstatic', '--noinput')
        
        self.stdout.write('Running migrations...')
        call_command('migrate', '--noinput')
        
        self.stdout.write(
            self.style.SUCCESS('Deployment preparation completed successfully!')
        )
