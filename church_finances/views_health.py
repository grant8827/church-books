from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.conf import settings

@csrf_exempt
def paypal_debug_config(request):
    """
    Temporary debug endpoint — shows masked PayPal config so you can verify
    Railway env vars are loaded correctly. Remove after debugging.
    """
    client_id = getattr(settings, 'PAYPAL_CLIENT_ID', '')
    secret = getattr(settings, 'PAYPAL_CLIENT_SECRET', '')
    return JsonResponse({
        'PAYPAL_MODE': getattr(settings, 'PAYPAL_MODE', '(not set)'),
        'USE_MOCK_PAYPAL': getattr(settings, 'USE_MOCK_PAYPAL', '(not set)'),
        'PAYPAL_CLIENT_ID_prefix': client_id[:12] + '...' if client_id else '(empty)',
        'PAYPAL_CLIENT_ID_length': len(client_id),
        'PAYPAL_CLIENT_SECRET_prefix': secret[:8] + '...' if secret else '(empty)',
        'PAYPAL_CLIENT_SECRET_length': len(secret),
    })

@csrf_exempt
def health_check(request):
    """
    Simple view to respond to health checks.
    Returns a 200 OK response with a simple message.
    This view is exempt from CSRF protection as it's used by Railway for health checks.
    """
    # Get CSRF token to initialize session if needed
    if request.method == 'GET':
        get_token(request)
    return HttpResponse("OK", content_type="text/plain")
