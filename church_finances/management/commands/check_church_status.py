"""
Django management command to check and fix church approval status
Usage: python manage.py check_church_status
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from church_finances.models import Church, ChurchMember

class Command(BaseCommand):
    help = 'Check and display church approval status'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Church Approval Status Report'))
        self.stdout.write('=' * 50)
        
        # Show all churches and their status
        churches = Church.objects.all()
        
        for church in churches:
            status = "✅ APPROVED" if church.is_approved else "⏳ PENDING"
            payment_status = church.payment_method.upper()
            
            self.stdout.write(f"\nChurch: {church.name}")
            self.stdout.write(f"Status: {status}")
            self.stdout.write(f"Payment Method: {payment_status}")
            self.stdout.write(f"Subscription Status: {church.subscription_status}")
            
            if church.payment_method == 'offline':
                verified = "✅ VERIFIED" if church.offline_verified_at else "⏳ PENDING"
                self.stdout.write(f"Offline Payment: {verified}")
                if church.offline_payment_reference:
                    self.stdout.write(f"Payment Reference: {church.offline_payment_reference}")
            
            # Show members for this church
            members = ChurchMember.objects.filter(church=church)
            self.stdout.write(f"Members ({members.count()}):")
            for member in members:
                active_status = "✅ ACTIVE" if member.is_active else "❌ INACTIVE"
                user_status = "✅ ACTIVE" if member.user.is_active else "❌ INACTIVE"
                self.stdout.write(f"  - {member.user.username} ({member.role}) - Member: {active_status}, User: {user_status}")
            
            self.stdout.write("-" * 40)
        
        # Show pending churches specifically
        pending_churches = Church.objects.filter(is_approved=False)
        if pending_churches:
            self.stdout.write(f"\n⚠️  {pending_churches.count()} churches need approval:")
            for church in pending_churches:
                self.stdout.write(f"  - {church.name} ({church.email})")