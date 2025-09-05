from django.http import HttpResponse

def health_check(request):
    """
    Simple view to respond to health checks.
    Returns a 200 OK response with a simple message.
    """
    return HttpResponse("OK", content_type="text/plain")
