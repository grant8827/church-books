from django.shortcuts import render
from django.http import HttpResponse
from django.template.loader import get_template
from django.template import Context
import traceback

def debug_home_view(request):
    """Debug view to test home page rendering"""
    try:
        # Try to render the home template
        template = get_template('home.html')
        context = {
            'user': request.user,
            'debug': True
        }
        content = template.render(context, request)
        return HttpResponse(content)
    except Exception as e:
        # Return detailed error information
        error_info = f"""
        <html>
        <body>
        <h1>Debug Home View Error</h1>
        <h2>Exception: {str(e)}</h2>
        <h3>Traceback:</h3>
        <pre>{traceback.format_exc()}</pre>
        </body>
        </html>
        """
        return HttpResponse(error_info, status=500)

def simple_home_view(request):
    """Simplified home view without template"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Church Books - Test</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            .error { color: red; }
            .success { color: green; }
        </style>
    </head>
    <body>
        <h1>Church Books - Debug Mode</h1>
        <p class="success">✅ Basic Django view is working!</p>
        <p>User authenticated: {}</p>
        <p>Request path: {}</p>
        <p>Request method: {}</p>
        
        <h2>Next Steps:</h2>
        <ul>
            <li><a href="/finances/login/">Test Login</a></li>
            <li><a href="/finances/subscription/">Test Subscription</a></li>
            <li><a href="/admin/">Admin</a></li>
        </ul>
    </body>
    </html>
    """.format(
        request.user.is_authenticated,
        request.path,
        request.method
    )
    return HttpResponse(html_content)