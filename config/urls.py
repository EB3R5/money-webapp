"""URL root: the admin, the health probe, the error handlers, and every page module's
patterns in `app/urls.py` (the one place a page module is registered)."""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.generic import RedirectView

from app.middleware import error_page
from app.urls import urlpatterns as app_patterns


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def healthz(request):
    return JsonResponse({"ok": True})


def not_found(request, exception=None):
    if request.path.startswith("/api/"):
        return JsonResponse({"detail": "Not Found"}, status=404)
    return error_page(request, 404, "Not found.")


def server_error(request):
    return error_page(request, 500, "Something went wrong. It has been logged.")


handler404 = not_found
handler500 = server_error

urlpatterns = [
    # One login, rate-limited: the admin's own form is never shown.
    path("admin/login/", RedirectView.as_view(url="/login?next=/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    *app_patterns,
]
