"""
Security middleware to handle common attack patterns and unwanted requests
"""

from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)

class SecurityMiddleware:
    """
    Middleware to handle common security-related requests and block unwanted traffic
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Common attack patterns to block
        self.blocked_paths = [
            '/wp-admin/',
            '/wordpress/',
            '/wp-includes/',
            '/wp-content/',
            '/xmlrpc.php',
            '/blog/',
            '/phpmyadmin/',
            '/admin.php',
            '/setup-config.php',
            '/core.js',
            '/jquery.js',
            '/wlwmanifest.xml',
        ]
        
        # File extensions to block
        self.blocked_extensions = [
            '.php',
            '.asp',
            '.aspx',
            '.jsp',
        ]
    
    def __call__(self, request):
        # Check if the request path contains blocked patterns
        path = request.path.lower()
        
        # Block WordPress and other CMS-related requests
        for blocked_path in self.blocked_paths:
            if blocked_path in path:
                logger.warning(f"Blocked security-related request: {request.path} from {request.META.get('REMOTE_ADDR', 'Unknown IP')}")
                return HttpResponse("Not Found", status=404)
        
        # Block requests for certain file extensions (except for legitimate static files)
        if not path.startswith('/static/') and not path.startswith('/media/'):
            for ext in self.blocked_extensions:
                if path.endswith(ext):
                    logger.warning(f"Blocked file extension request: {request.path} from {request.META.get('REMOTE_ADDR', 'Unknown IP')}")
                    return HttpResponse("Not Found", status=404)
        
        # Handle favicon requests
        if path == '/favicon.ico':
            return redirect('/static/images/logo.png')
        
        response = self.get_response(request)
        return response


class TrialExpirationMiddleware:
    """
    Middleware to restrict access to all features when a church's trial has expired
    and they haven't paid yet. Redirects expired trial users to payment page.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Paths that are allowed even when trial has expired
        self.allowed_paths = [
            '/finances/login/',
            '/finances/logout/',
            '/finances/trial-expired/',
            '/finances/paypal/pay/',
            '/finances/paypal/activate/',
            '/finances/paypal/webhook/',
            '/finances/stripe/pay/',
            '/finances/stripe/create-checkout/',
            '/finances/stripe/success/',
            '/finances/stripe/cancel/',
            '/finances/stripe/webhook/',
            '/finances/subscription/',
            '/finances/pending-approval/',
            '/finances/account-status/',
            '/static/',
            '/media/',
            '/admin/',  # Allow admin access
            '/about/',
            '/contact/',
            '/pricing/',
            '/password_reset/',
            '/reset/',
        ]
    
    def __call__(self, request):
        # Skip middleware for non-authenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)
        
        # Skip middleware for superusers
        if request.user.is_superuser:
            return self.get_response(request)
        
        # Check if path is allowed
        path = request.path
        if any(path.startswith(allowed) for allowed in self.allowed_paths):
            return self.get_response(request)
        
        # Check if user has a church membership
        try:
            from .models import ChurchMember
            member = ChurchMember.objects.filter(user=request.user).first()
            
            if member and member.church:
                church = member.church
                
                # If trial is expired AND subscription is not active, block access
                if church.is_trial_expired and church.subscription_status != 'active':
                    logger.info(f"Blocking access for expired trial user: {request.user.username} at {path}")
                    return redirect('trial_expired_payment')
                
        except Exception as e:
            logger.error(f"Error in TrialExpirationMiddleware: {e}")
            # Don't block on errors, let the request through
            pass
        
        response = self.get_response(request)
        return response