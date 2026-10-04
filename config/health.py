from django.db import connection
from django.http import JsonResponse
from rest_framework import status


def health(request):
    checks = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"

    healthy = all(v == "ok" for v in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "unhealthy", "checks": checks},
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
