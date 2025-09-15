from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .views_subscription import get_paypal_service

@require_http_methods(["GET"])
def debug_paypal_config(request):
    """
    Debug endpoint to check PayPal configuration
    Only accessible with debug key for security
    """
    debug_key = request.GET.get('debug_key')
    if debug_key != 'paypal_debug_2025':
        return JsonResponse({'error': 'Invalid debug key'}, status=403)
    
    try:
        # Get PayPal service
        service = get_paypal_service()
        
        config_info = {
            'USE_MOCK_PAYPAL': getattr(settings, 'USE_MOCK_PAYPAL', False),
            'PAYPAL_MODE': getattr(settings, 'PAYPAL_MODE', 'Not set'),
            'PAYPAL_CLIENT_ID': getattr(settings, 'PAYPAL_CLIENT_ID', 'Not set')[:10] + '...' if hasattr(settings, 'PAYPAL_CLIENT_ID') else 'Not set',
            'PAYPAL_CLIENT_SECRET': 'Set' if hasattr(settings, 'PAYPAL_CLIENT_SECRET') and settings.PAYPAL_CLIENT_SECRET else 'Not set',
            'service_type': type(service).__name__,
            'is_mock_service': hasattr(service, 'is_mock') and getattr(service, 'is_mock', False),
            'PAYPAL_BASE_URL': getattr(settings, 'PAYPAL_BASE_URL', 'Not set'),
        }
        
        # Test mock service
        if hasattr(service, 'is_mock') and service.is_mock:
            try:
                test_token = service.get_access_token()
                config_info['mock_token_test'] = 'Success' if test_token else 'Failed'
                config_info['mock_token_value'] = test_token[:20] + '...' if test_token else 'None'
            except Exception as e:
                config_info['mock_token_test'] = f'Error: {str(e)}'
        
        return JsonResponse({
            'status': 'success',
            'config': config_info,
            'debug_timestamp': str(timezone.now())
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'debug_timestamp': str(timezone.now())
        })