from django.http import JsonResponse
from django.db import connection
from django.conf import settings
from django.utils import timezone
import os

def debug_database(request):
    """
    Debug database connection - ONLY enable in production for troubleshooting
    Remove or secure this after fixing the issue
    """
    # Security check - only allow in specific conditions
    debug_key = request.GET.get('debug_key')
    if debug_key != 'railway_db_debug_2025':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    debug_info = {
        'timestamp': str(timezone.now()),
        'environment_variables': {
            'DATABASE_URL_EXISTS': bool(os.getenv('DATABASE_URL')),
            'DATABASE_URL_LENGTH': len(os.getenv('DATABASE_URL', '')) if os.getenv('DATABASE_URL') else 0,
            'PGHOST': os.getenv('PGHOST'),
            'PGPORT': os.getenv('PGPORT'), 
            'PGDATABASE': os.getenv('PGDATABASE'),
            'PGUSER': os.getenv('PGUSER'),
            'PGPASSWORD_EXISTS': bool(os.getenv('PGPASSWORD')),
            'POSTGRES_HOST': os.getenv('POSTGRES_HOST'),
            'POSTGRES_PORT': os.getenv('POSTGRES_PORT'),
            'POSTGRES_DB': os.getenv('POSTGRES_DB'),
            'POSTGRES_USER': os.getenv('POSTGRES_USER'),
            'POSTGRES_PASSWORD_EXISTS': bool(os.getenv('POSTGRES_PASSWORD')),
            'DB_HOST': os.getenv('DB_HOST'),
            'DB_PORT': os.getenv('DB_PORT'),
            'DB_NAME': os.getenv('DB_NAME'),
            'DB_USER': os.getenv('DB_USER'),
            'DB_PASSWORD_EXISTS': bool(os.getenv('DB_PASSWORD')),
        },
        'django_database_config': {},
        'connection_test': 'NOT_TESTED'
    }
    
    # Get Django database configuration
    try:
        db_config = connection.settings_dict
        debug_info['django_database_config'] = {
            'ENGINE': db_config.get('ENGINE'),
            'NAME': db_config.get('NAME'),
            'HOST': db_config.get('HOST'),
            'PORT': db_config.get('PORT'),
            'USER': db_config.get('USER'),
            'PASSWORD_EXISTS': bool(db_config.get('PASSWORD')),
            'OPTIONS': db_config.get('OPTIONS', {}),
        }
    except Exception as e:
        debug_info['django_database_config'] = f'ERROR: {str(e)}'
    
    # Test database connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            result = cursor.fetchone()
            debug_info['connection_test'] = f'SUCCESS: {result[0] if result else "Connected"}'
            
            # Test a simple query
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            migration_count = cursor.fetchone()[0]
            debug_info['migration_count'] = migration_count
            
    except Exception as e:
        debug_info['connection_test'] = f'FAILED: {str(e)}'
        debug_info['connection_error_type'] = type(e).__name__
    
    # Check Railway-specific environment variables
    railway_vars = {}
    for key, value in os.environ.items():
        if any(keyword in key.upper() for keyword in ['RAILWAY', 'DATABASE', 'POSTGRES', 'PG']):
            if 'PASSWORD' in key.upper() or 'SECRET' in key.upper():
                railway_vars[key] = bool(value)
            else:
                railway_vars[key] = value
    
    debug_info['railway_environment'] = railway_vars
    
    return JsonResponse(debug_info, json_dumps_params={'indent': 2})

def debug_auth(request):
    """
    Debug authentication system - secure endpoint
    """
    debug_key = request.GET.get('debug_key')
    if debug_key != 'railway_auth_debug_2025':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    auth_info = {
        'django_version': getattr(settings, 'DJANGO_VERSION', 'Unknown'),
        'debug_mode': settings.DEBUG,
        'allowed_hosts': settings.ALLOWED_HOSTS,
        'middleware': settings.MIDDLEWARE,
        'authentication_backends': getattr(settings, 'AUTHENTICATION_BACKENDS', []),
        'session_engine': getattr(settings, 'SESSION_ENGINE', 'Unknown'),
        'csrf_trusted_origins': getattr(settings, 'CSRF_TRUSTED_ORIGINS', []),
    }
    
    # Test user model
    try:
        from django.contrib.auth.models import User
        user_count = User.objects.count()
        superuser_count = User.objects.filter(is_superuser=True).count()
        auth_info['user_stats'] = {
            'total_users': user_count,
            'superusers': superuser_count
        }
    except Exception as e:
        auth_info['user_stats'] = f'ERROR: {str(e)}'
    
    return JsonResponse(auth_info, json_dumps_params={'indent': 2})