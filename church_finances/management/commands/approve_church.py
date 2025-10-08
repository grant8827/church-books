"""
Django management command to approve churches
Usage: python manage.py approve_church --church-name "Your Church Name"
       python manage.py approve_church --all-pending
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from church_finances.models import Church, ChurchMember

class Command(BaseCommand):
    help = 'Approve churches and activate their members'

    def add_arguments(self, parser):
        parser.add_argument('--church-name', type=str, help='Name of the church to approve')
        parser.add_argument('--all-pending', action='store_true', help='Approve all pending churches')

    def handle(self, *args, **options):
        church_name = options.get('church_name')
        all_pending = options.get('all_pending')
        
        if church_name:
            try:
                church = Church.objects.get(name__icontains=church_name, is_approved=False)
                self.approve_church(church)
            except Church.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Church "{church_name}" not found or already approved'))
            except Church.MultipleObjectsReturned:
                churches = Church.objects.filter(name__icontains=church_name, is_approved=False)
                self.stdout.write(self.style.WARNING(f'Multiple churches found with "{church_name}":'))
                for i, church in enumerate(churches, 1):
                    self.stdout.write(f'{i}. {church.name} ({church.email})')
                
        elif all_pending:
            pending_churches = Church.objects.filter(is_approved=False)
            if not pending_churches:
                self.stdout.write(self.style.SUCCESS('No pending churches to approve'))
                return
                
            for church in pending_churches:
                self.approve_church(church)
        else:
            self.stdout.write(self.style.ERROR('Please specify --church-name or --all-pending'))

    def approve_church(self, church):
        # Approve the church
        church.is_approved = True
        church.subscription_status = 'active'
        
        # Set subscription dates if not already set
        if not church.subscription_start_date:
            church.subscription_start_date = timezone.now()
        if not church.subscription_end_date:
            church.subscription_end_date = timezone.now() + timedelta(days=365)
            
        # For offline payments, mark as verified if not already
        if church.payment_method == 'offline' and not church.offline_verified_at:
            church.offline_verified_at = timezone.now()
            church.offline_payment_reference = f'ADMIN_APPROVED_{church.id}'
            
        church.save()
        
        # Activate all members and users for this church
        members = ChurchMember.objects.filter(church=church)
        activated_users = []
        
        for member in members:
            if not member.user.is_active:
                member.user.is_active = True
                member.user.save()
                activated_users.append(member.user.username)
            if not member.is_active:
                member.is_active = True
                member.save()
        
        self.stdout.write(self.style.SUCCESS(f'✅ Approved: {church.name}'))
        if activated_users:
            self.stdout.write(f'   Activated users: {", ".join(activated_users)}')