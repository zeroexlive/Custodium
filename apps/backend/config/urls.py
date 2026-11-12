from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import path

from waas.api.router import api


def healthz(request):
    """Liveness: the process is up. No dependencies checked."""
    return JsonResponse({"status": "ok"})


def readyz(request):
    """Readiness: the database answers. Used by orchestrators
    to gate traffic during deploys and failovers."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - readiness must not leak details
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    path("healthz", healthz),
    path("readyz", readyz),
]
