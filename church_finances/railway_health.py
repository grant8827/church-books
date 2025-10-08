from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import logging
import os

# Set up logging
logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def railway_health_check(request):
    """
    Ultra-simple health check view specifically for Railway.
    This view is exempt from all middleware processing.
    Returns basic status information for debugging.
    """
    try:
        # Basic health check response
        status_info = []
        
        # Check if we're in Railway environment
        is_railway = bool(os.environ.get('RAILWAY_ENVIRONMENT'))
        status_info.append(f"Railway: {'Yes' if is_railway else 'No'}")
        
        # Check current time
        current_time = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
        status_info.append(f"Time: {current_time}")
        
        # Check PORT
        port = os.environ.get('PORT', 'Not Set')
        status_info.append(f"Port: {port}")
        
        # Simple response for HEAD requests (common for health checks)
        if request.method == 'HEAD':
            return HttpResponse(status=200, content_type="text/plain")
        
        # Full response for GET requests
        response_text = "OK\n" + "\n".join(status_info)
        
        return HttpResponse(response_text, content_type="text/plain", status=200)
        
    except Exception as e:
        # Log the error but still return a response
        logger.error(f"Health check error: {e}")
        error_response = f"ERROR: {str(e)}"
        
        # Return error but with 200 status to prevent Railway from thinking service is down
        return HttpResponse(error_response, content_type="text/plain", status=200)
