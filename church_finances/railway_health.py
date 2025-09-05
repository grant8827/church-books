from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

@csrf_exempt
@require_GET
def railway_health_check(request):
    """
    Ultra-simple health check view specifically for Railway.
    This view is exempt from all middleware processing.
    """
    return HttpResponse("OK", content_type="text/plain")
