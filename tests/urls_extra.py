"""Test-only routes beside the app's (tests set ROOT_URLCONF to this module): a view that
raises, for the error boundary, and one that owns its frame headers."""

from django.http import HttpResponse
from django.urls import path

from config.urls import handler404, handler500, urlpatterns as base  # noqa: F401


def boom(request):
    raise RuntimeError("secret detail https://u:p@host/x")


def boom_after_write(request):
    from app.store.transactions import transactions
    transactions.insert({"_id": "boom", "Description": "never committed", "Amount": 1.0})
    raise RuntimeError("after the write")


def framed(request):
    return HttpResponse("x", headers={"Content-Security-Policy": "sandbox", "X-Frame-Options": "SAMEORIGIN",
                                      "Cache-Control": "public"})


urlpatterns = [path("__boom", boom), path("__boom_after_write", boom_after_write),
               path("_test/framed", framed), *base]
