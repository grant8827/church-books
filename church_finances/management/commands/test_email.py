from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings


class Command(BaseCommand):
    help = 'Test email configuration by sending a test email'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            type=str,
            help='Email address to send test email to',
            required=True
        )

    def handle(self, *args, **options):
        recipient_email = options['to']
        
        try:
            self.stdout.write(f"Attempting to send test email to {recipient_email}...")
            self.stdout.write(f"Using EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
            
            if hasattr(settings, 'EMAIL_HOST'):
                self.stdout.write(f"EMAIL_HOST: {settings.EMAIL_HOST}")
                self.stdout.write(f"EMAIL_PORT: {settings.EMAIL_PORT}")
                self.stdout.write(f"EMAIL_USE_SSL: {getattr(settings, 'EMAIL_USE_SSL', False)}")
                self.stdout.write(f"EMAIL_USE_TLS: {getattr(settings, 'EMAIL_USE_TLS', False)}")
                self.stdout.write(f"EMAIL_HOST_USER: {getattr(settings, 'EMAIL_HOST_USER', 'Not set')}")
            
            send_mail(
                subject='Church Finance App - SMTP Test Email',
                message='''
Hello,

This is a test email to verify that your SMTP configuration is working correctly.

If you receive this email, your Church Finance App is properly configured to send emails using:
- Host: webhosting2023.is.cc
- Port: 465 (SSL)
- From: info@churchbooksmanagement.com

Best regards,
Church Finance App System
                ''',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email],
                fail_silently=False,
            )
            
            self.stdout.write(
                self.style.SUCCESS(f'Test email successfully sent to {recipient_email}!')
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to send email: {str(e)}')
            )