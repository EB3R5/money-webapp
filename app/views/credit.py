"""Credit page — the registry + score log + activity log (stored), with Summary and Strategy
computed live from those plus the shared balanceHistory/transactions data. Thin HTTP adapter
over app/credit.py through the shared guard()/read_body() seam."""

from django.urls import path

from .. import credit, web


@web.GET
def credit_page(request):
    return web.page(request, "credit.html", {
        "config": credit.get_config(),
        "summary": credit.credit_summary(),
        "accounts": credit.list_accounts(),
        "scores": credit.list_scores(),
        "activity": credit.list_activity(),
        "strategy": credit.strategy(),
        "balance_options": credit.balance_account_options(),
        "falloff_categories": list(credit.FALLOFF_YEARS.keys()),
    })


@web.GET
def summary(request):
    return web.json(credit.credit_summary())


@web.POST
def config(request):
    return web.json(credit.set_config(web.read_json(request)))


# accounts
@web.POST
def add_account(request):
    return web.json(credit.add_account(web.read_json(request)))


@web.POST
def update_account(request):
    return web.json(credit.update_account(web.read_json(request)))


@web.POST
def delete_account(request):
    return web.json(credit.delete_account(web.read_json(request)))


# scores
@web.POST
def add_score(request):
    return web.json(credit.add_score(web.read_json(request)))


@web.POST
def delete_score(request):
    return web.json(credit.delete_score(web.read_json(request)))


# activity
@web.POST
def add_activity(request):
    return web.json(credit.add_activity(web.read_json(request)))


@web.POST
def delete_activity(request):
    return web.json(credit.delete_activity(web.read_json(request)))


urlpatterns = [
    path("credit", credit_page),
    path("api/credit/summary", summary),
    path("api/credit/config", config),
    path("api/credit/accounts", add_account),
    path("api/credit/accounts/update", update_account),
    path("api/credit/accounts/delete", delete_account),
    path("api/credit/scores", add_score),
    path("api/credit/scores/delete", delete_score),
    path("api/credit/activity", add_activity),
    path("api/credit/activity/delete", delete_activity),
]
