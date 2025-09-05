from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def health_check(request):
    """
    Simple view to respond to health checks.
    Returns a 200 OK response with a simple message.
    This view is exempt from CSRF protection as it's used by Railway for health checks.
    """
    return HttpResponse("OK", content_type="text/plain")
