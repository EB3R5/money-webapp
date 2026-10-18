"""Settings → Appearance: the chart colors panel on its own page, and the one route that
saves it — the same panel sits folded on the Dashboard and posts here too. The rows the
panel renders come with every page (the `chart_colors` context processor). `next` says
where to return to; only a path on this site is honoured."""

from django.urls import path

from .. import chart_colors, web


def _next(request) -> str:
    target = request.POST.get("next", "") or request.GET.get("next", "")
    return target if target.startswith("/") and not target.startswith("//") else "/settings/appearance"


@web.GET
def appearance_page(request):
    return web.page(request, "settings_appearance.html")


@web.POST
def save_chart_colors(request):
    raw = {} if "reset" in request.POST else request.POST
    try:
        chart_colors.save(request.user, raw)
    except ValueError as e:
        return web.page(request, "settings_appearance.html", {"error": str(e)}, status=400)
    return web.redirect(_next(request))


urlpatterns = [
    path("settings/appearance", appearance_page),
    path("settings/appearance/chart-colors", save_chart_colors),
]
