"""
Security middleware to handle common attack patterns and unwanted requests
"""

from django.http import HttpResponse
from django.shortcuts import redirect
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