import os
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.db import connection
from django.conf import settings

@csrf_exempt
@require_GET
def railway_db_health_check(request):
    """
    Comprehensive database health check for Railway deployment.
    Shows database connection status and environment variables.
    """
    health_data = {
        'database_status': 'unknown',
        'environment_vars': {},
        'database_config': {},
        'connection_test': 'not_tested'
    }
    
    # Check environment variables
    env_vars = [
        'DATABASE_URL', 'PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD',
        'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD',
        'DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD'
    ]
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            # Mask passwords for security
            if 'PASSWORD' in var.upper():
                health_data['environment_vars'][var] = '***masked***'
            else:
                health_data['environment_vars'][var] = value
    
    # Get database configuration
    try:
        db_config = settings.DATABASES['default']
        health_data['database_config'] = {
            'ENGINE': db_config.get('ENGINE'),
            'HOST': db_config.get('HOST'),
            'PORT': db_config.get('PORT'),
            'NAME': db_config.get('NAME'),
            'USER': db_config.get('USER'),
            'PASSWORD': '***masked***' if db_config.get('PASSWORD') else None,
        }
    except Exception as e:
        health_data['database_config'] = {'error': str(e)}
    
    # Test database connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            if result and result[0] == 1:
                health_data['database_status'] = 'connected'
                health_data['connection_test'] = 'success'
            else:
                health_data['database_status'] = 'connected_but_query_failed'
                health_data['connection_test'] = 'query_failed'
    except Exception as e:
        health_data['database_status'] = 'connection_failed'
        health_data['connection_test'] = str(e)
    
    # Return appropriate response
    if health_data['database_status'] == 'connected':
        status_code = 200
        message = "Database connection healthy"
    else:
        status_code = 503
        message = "Database connection issues detected"
    
    # Plain text response for simple health checks
    if request.GET.get('format') == 'text':
        return HttpResponse(
            f"{message}\nStatus: {health_data['database_status']}\nTest: {health_data['connection_test']}", 
            content_type="text/plain",
            status=status_code
        )
    
    # JSON response with full details
    health_data['message'] = message
    return JsonResponse(health_data, status=status_code)

@csrf_exempt
@require_GET
def railway_env_debug(request):
    """
    Debug view to show all Railway environment variables.
    Only accessible in development or with special header.
    """
    # Security check - only show in debug mode or with special header
    if not settings.DEBUG and request.headers.get('X-Railway-Debug') != 'true':
        return HttpResponse("Not authorized", status=403)
    
    env_vars = {}
    for key, value in os.environ.items():
        if any(keyword in key.upper() for keyword in ['DB', 'POSTGRES', 'PG', 'DATABASE', 'RAILWAY']):
            # Mask sensitive information
            if 'PASSWORD' in key.upper() or 'SECRET' in key.upper() or 'TOKEN' in key.upper():
                env_vars[key] = '***masked***'
            else:
                env_vars[key] = value
    
    return JsonResponse({
        'environment_variables': env_vars,
        'total_vars': len(env_vars),
        'debug_mode': settings.DEBUG
    }, json_dumps_params={'indent': 2})