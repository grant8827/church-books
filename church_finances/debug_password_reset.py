"""
Debug view to test password reset functionality
"""
from django.http import HttpResponse
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from django.shortcuts import get_object_or_404

def debug_password_reset(request, uidb64, token):
    """Debug view to check password reset token validation"""
    debug_info = []
    
    debug_info.append(f"URL Parameters:")
    debug_info.append(f"  uidb64: {uidb64}")
    debug_info.append(f"  token: {token}")
    debug_info.append("")
    
    try:
        # Try to decode the uidb64
        uid = urlsafe_base64_decode(uidb64).decode()
        debug_info.append(f"Decoded UID: {uid}")
        
        # Try to get the user
        user = get_object_or_404(User, pk=uid)
        debug_info.append(f"Found user: {user} (ID: {user.id}, Email: {user.email})")
        debug_info.append("")
        
        # Test token validation
        token_valid = default_token_generator.check_token(user, token)
        debug_info.append(f"Token validation result: {token_valid}")
        
        if not token_valid:
            debug_info.append("Token validation failed. Possible reasons:")
            debug_info.append("- Token has expired (24 hours)")
            debug_info.append("- Token has already been used")
            debug_info.append("- User password has changed since token generation")
            debug_info.append("- System time/timezone issues")
            
        debug_info.append("")
        debug_info.append(f"User details:")
        debug_info.append(f"  Last login: {user.last_login}")
        debug_info.append(f"  Date joined: {user.date_joined}")
        debug_info.append(f"  Is active: {user.is_active}")
        
    except Exception as e:
        debug_info.append(f"Error: {str(e)}")
        import traceback
        debug_info.append(f"Traceback: {traceback.format_exc()}")
    
    return HttpResponse("<pre>" + "\n".join(debug_info) + "</pre>")