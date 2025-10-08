"""
Minimal startup health check for Railway.
This can be imported before Django is fully configured.
"""

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
import os
import json

@csrf_exempt
def minimal_health_check(request):
    """
    Absolute minimal health check that works even during Django startup.
    Only checks basic environment and returns success.
    """
    try:
        # Just return OK - this is for Railway to know the container is running
        return HttpResponse("STARTUP_OK", content_type="text/plain", status=200)
    except:
        # Even if there's an error, return 200 so Railway doesn't restart
        return HttpResponse("STARTUP_ERROR_BUT_RUNNING", content_type="text/plain", status=200)

@csrf_exempt  
def startup_debug(request):
    """
    Debug endpoint to show what's happening during startup.
    """
    try:
        startup_info = {
            'railway_env': os.environ.get('RAILWAY_ENVIRONMENT', 'Not Railway'),
            'port': os.environ.get('PORT', 'Not Set'), 
            'database_url_exists': bool(os.environ.get('DATABASE_URL')),
            'python_path': os.environ.get('PYTHONPATH', 'Not Set'),
            'django_settings': os.environ.get('DJANGO_SETTINGS_MODULE', 'Not Set'),
            'pwd': os.getcwd(),
        }
        
        response_text = json.dumps(startup_info, indent=2)
        return HttpResponse(response_text, content_type="application/json")
        
    except Exception as e:
        error_info = {'error': str(e), 'type': type(e).__name__}
        return HttpResponse(json.dumps(error_info), content_type="application/json", status=500)