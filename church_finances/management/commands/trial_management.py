from django.core.management.base import BaseCommand
from django.utils import timezone
from church_finances.models import Church
from datetime import timedelta

class Command(BaseCommand):
    help = 'Manage trial system for churches'

    def add_arguments(self, parser):
        parser.add_argument(
            '--list-trials',
            action='store_true',
            help='List all churches with trial information',
        )
        parser.add_argument(
            '--expire-church',
            type=str,
            help='Expire trial for a specific church (by name or ID)',
        )
        parser.add_argument(
            '--extend-trial',
            type=str,
            help='Extend trial by 30 days for a specific church (by name or ID)',
        )
        parser.add_argument(
            '--reset-trials',
            action='store_true',
            help='Reset all churches to 30-day trial (for testing)',
        )

    def handle(self, *args, **options):
        if options['list_trials']:
            self.list_trials()
        elif options['expire_church']:
            self.expire_church_trial(options['expire_church'])
        elif options['extend_trial']:
            self.extend_trial(options['extend_trial'])
        elif options['reset_trials']:
            self.reset_all_trials()
        else:
            self.stdout.write('Use --help to see available options')

    def list_trials(self):
        self.stdout.write(self.style.SUCCESS('\n=== TRIAL SYSTEM STATUS ===\n'))
        
        churches = Church.objects.all()
        for church in churches:
            status = "ACTIVE" if church.is_trial_active else "INACTIVE"
            expired = "EXPIRED" if church.is_trial_expired else "VALID"
            days_remaining = church.trial_days_remaining
            can_access = "YES" if church.can_access_dashboard else "NO"
            
            self.stdout.write(f"Church: {church.name}")
            self.stdout.write(f"  Trial Status: {status}")
            self.stdout.write(f"  Trial Validity: {expired}")
            self.stdout.write(f"  Days Remaining: {days_remaining}")
            self.stdout.write(f"  Can Access Dashboard: {can_access}")
            self.stdout.write(f"  Trial Start: {church.trial_start_date}")
            self.stdout.write(f"  Trial End: {church.trial_end_date}")
            self.stdout.write(f"  Payment Verified: {'YES' if church.is_payment_verified else 'NO'}")
            self.stdout.write(f"  Subscription Status: {church.subscription_status}")
            self.stdout.write("-" * 50)

    def expire_church_trial(self, church_identifier):
        try:
            # Try to find church by ID first, then by name
            try:
                church = Church.objects.get(id=int(church_identifier))
            except (ValueError, Church.DoesNotExist):
                church = Church.objects.get(name__icontains=church_identifier)
            
            # Set trial as expired
            church.trial_end_date = timezone.now() - timedelta(days=1)
            church.save()
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully expired trial for church: {church.name}')
            )
        except Church.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Church not found: {church_identifier}')
            )

    def extend_trial(self, church_identifier):
        try:
            # Try to find church by ID first, then by name
            try:
                church = Church.objects.get(id=int(church_identifier))
            except (ValueError, Church.DoesNotExist):
                church = Church.objects.get(name__icontains=church_identifier)
            
            # Extend trial by 30 days from current end date or now
            if church.trial_end_date:
                church.trial_end_date = church.trial_end_date + timedelta(days=30)
            else:
                church.trial_end_date = timezone.now() + timedelta(days=30)
            
            church.is_trial_active = True
            church.save()
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully extended trial for church: {church.name}')
            )
        except Church.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Church not found: {church_identifier}')
            )

    def reset_all_trials(self):
        churches = Church.objects.all()
        for church in churches:
            church.trial_start_date = timezone.now()
            church.trial_end_date = timezone.now() + timedelta(days=30)
            church.is_trial_active = True
            church.trial_expired_notified = False
            church.save()
        
        self.stdout.write(
            self.style.SUCCESS(f'Reset trials for {churches.count()} churches')
        )