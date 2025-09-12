from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from church_finances.models import Church, ChurchMember

class Command(BaseCommand):
    help = 'Fix user authentication issues - create missing ChurchMember records and reset passwords'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting user authentication fixes...'))
        
        # Fix grant8827 user
        try:
            user = User.objects.get(username='grant8827')
            self.stdout.write(f'Found user: {user.username}')
            
            # Create ChurchMember if doesn't exist
            member, created = ChurchMember.objects.get_or_create(
                user=user,
                defaults={
                    'church': Church.objects.filter(is_approved=True).first(),
                    'role': 'admin',
                    'is_active': True,
                    'phone_number': '555-0000',
                    'address': 'Admin Address'
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created ChurchMember record for {user.username}'))
            else:
                self.stdout.write(f'ChurchMember already exists for {user.username}')
            
            # Reset password
            user.set_password('password123')
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Reset password for {user.username}'))
            
        except User.DoesNotExist:
            self.stdout.write(self.style.WARNING('grant8827 user not found'))
        
        # Check other users
        for username in ['jdoe', 'jbrown']:
            try:
                user = User.objects.get(username=username)
                # Ensure password is set to password123
                user.set_password('password123')
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Confirmed password for {username}'))
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'{username} user not found'))
        
        # Display status
        self.stdout.write('\n' + '='*50)
        self.stdout.write('USER STATUS SUMMARY:')
        self.stdout.write('='*50)
        
        for username in ['grant8827', 'jdoe', 'jbrown']:
            try:
                user = User.objects.get(username=username)
                self.stdout.write(f'{username}:')
                self.stdout.write(f'  - Active: {user.is_active}')
                self.stdout.write(f'  - Superuser: {user.is_superuser}')
                
                try:
                    member = ChurchMember.objects.get(user=user)
                    self.stdout.write(f'  - Church: {member.church.name}')
                    self.stdout.write(f'  - Church Approved: {member.church.is_approved}')
                    self.stdout.write(f'  - Member Active: {member.is_active}')
                except ChurchMember.DoesNotExist:
                    self.stdout.write(f'  - No ChurchMember record')
                    
            except User.DoesNotExist:
                self.stdout.write(f'{username}: NOT FOUND')
        
        self.stdout.write('\n' + self.style.SUCCESS('User authentication fixes completed!'))
        self.stdout.write('All users should now be able to log in with password: password123')