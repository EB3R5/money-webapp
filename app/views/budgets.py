"""Budgets — write and store budget versions.

Two pages: a version list (browse/new/delete) and a per-version grid editor where each
spending Group's planned amount is edited inline. The seeding maths + the budgets data
model live in app/budgets.py; this file is the HTTP + persistence adapter.

Lines are rows of the budget_lines store keyed by version (a budget is a few dozen
groups, not a 14k-row table), so edits are small per-line writes rather than the Grid
per-row CRUD the big grids use."""

from django.urls import path

from .. import budgets as engine
from .. import web
from ..store.budget_lines import budget_lines
from ..store.budgets import budgets
from ..store.deletions import deletions
from ..values import parse_amount
from ..web import DomainError



def _amount(v) -> float:
    """Grid value → stored number ('$1,200' → 1200.0); blank/em-dash → 0."""
    if v == "—":
        return 0.0
    return parse_amount(v, "amount", blank=0.0)


def _touch(budget_id: str) -> bool:
    """Stamp the version edited; False when it doesn't exist."""
    return budgets.update(budget_id, {})


# --- pages -----------------------------------------------------------------

@web.GET
def budgets_page(request):
    return web.page(request, "budgets.html",
                    {"versions": engine.list_versions(), "month": engine.current_month()})


@web.GET
def pivot_page(request):
    """Cross-version pivot: planned amount per Group across every budget version, rendered
    natively (no AG Grid). Registered before /<budget_id> so 'pivot' isn't read as an id."""
    data = engine.build_version_pivot()
    return web.page(request, "budget_pivot.html", {"versions": data["versions"], "table": data["table"]})


@web.GET
def report_page(request, budget_id: str):
    """Budget-vs-Actual: each group's planned amount vs actual spend that month,
    with the v2 variance / score / alert columns and conditional formatting."""
    doc = engine.load_budget(budget_id)
    if doc is None:
        return web.redirect("/budgets")
    rows = engine.build_report(doc)
    return web.page(
        request, "budget_report.html",
        {
            "budget": {"id": doc["_id"], "budgetId": doc.get("budgetId", ""),
                       "versionName": doc.get("versionName", ""), "month": doc.get("month", "")},
            "rows": rows,
            "summary": {
                "rows": len(rows),
                "on_target": sum(1 for r in rows if r["alert_level"] == "On Target"),
                "unbudgeted": sum(1 for r in rows if r["match"] == "actual_only"),
                "budget_only": sum(1 for r in rows if r["match"] == "budget_only"),
                "budget_total": round(sum(r["budget_amount"] for r in rows), 2),
                # Sums every row, so spend with no line counts too.
                "actual_total": round(sum(r["actual_amount"] for r in rows), 2),
            },
        },
    )


@web.GET
def editor_page(request, budget_id: str):
    doc = engine.load_budget(budget_id)
    if doc is None:
        return web.redirect("/budgets")
    return web.page(
        request, "budget_editor.html",
        {
            "budget": {
                "id": doc["_id"], "budgetId": doc.get("budgetId", ""),
                "versionName": doc.get("versionName", ""), "month": doc.get("month", ""),
                "status": doc.get("status", "draft"),
            },
            "lines": doc.get("lines") or [],
            "groups": engine.all_groups(),
        },
    )


# --- version lifecycle -----------------------------------------------------

@web.POST
def new_budget(request):
    """Create a draft seeded from trailing history. Body: {month, versionName}."""
    body = web.read_json(request)
    try:
        doc = engine.create_draft(body.get("month"), body.get("versionName"))
    except ValueError as e:
        return web.json({"ok": False, "error": str(e)}, 400)
    return web.json({"ok": True, "id": doc["_id"]})


@web.POST
def save_budget(request, budget_id: str):
    """Mark the version saved (it already persists on every edit)."""
    return web.json({"ok": budgets.update(budget_id, {"status": "saved"})})


@web.POST
def delete_budget(request, budget_id: str):
    """Audit the version with its lines embedded, then delete it (lines cascade)."""
    doc = engine.load_budget(budget_id)
    if doc is None:
        return web.json({"ok": False})
    deletions.log("budgets", [doc])
    budgets.delete(budget_id)
    return web.json({"ok": True})


# --- line editing ----------------------------------------------------------

@web.POST
def update_line(request, budget_id: str):
    """Inline amount edit. Body: {group, amount}."""
    body = web.read_json(request)
    group = (body.get("group") or "").strip()
    if not group:
        return web.json({"ok": False, "error": "missing group"}, 400)
    try:
        amount = _amount(body.get("amount"))
    except DomainError:
        return web.json({"ok": False, "error": "amount not a number"}, 400)
    line = budget_lines.one({"budget": budget_id, "group": group})
    if line is None:
        return web.json({"ok": False, "amount": amount})
    budget_lines.update(line["_id"], {"amount": amount, "source": "manual"})
    _touch(budget_id)
    return web.json({"ok": True, "amount": amount})


@web.POST
def add_line(request, budget_id: str):
    """Add a group line. Body: {group, amount}. No-op if the group already exists."""
    body = web.read_json(request)
    group = (body.get("group") or "").strip()
    if not group:
        return web.json({"ok": False, "error": "missing group"}, 400)
    try:
        amount = _amount(body.get("amount"))
    except DomainError:
        return web.json({"ok": False, "error": "amount not a number"}, 400)
    if budget_lines.one({"budget": budget_id, "group": group}):
        return web.json({"ok": False, "error": "group already in budget"}, 409)
    line = {"group": group, "amount": amount, "source": "manual", "dataPoints": 0}
    if not _touch(budget_id):
        return web.json({"ok": False, "line": line})
    position = budget_lines.count({"budget": budget_id})
    budget_lines.insert({"budget": budget_id, "position": position, **line})
    return web.json({"ok": True, "line": line})


@web.POST
def delete_lines(request, budget_id: str):
    """Remove lines. Body: {groups: [...]}."""
    body = web.read_json(request)
    groups = body.get("groups") or []
    if not groups:
        return web.json({"ok": False, "error": "no groups"}, 400)
    if not _touch(budget_id):
        return web.json({"ok": False})
    budget_lines.delete_where(budget=budget_id, group=groups)
    return web.json({"ok": True})


# Full paths (the FastAPI router had a /budgets prefix); the fixed segments precede
# /budgets/<budget_id>, which would otherwise read "pivot" or "api" as an id.
urlpatterns = [
    path("budgets", budgets_page),
    path("budgets/pivot", pivot_page),
    path("budgets/api/new", new_budget),
    path("budgets/api/<str:budget_id>/save", save_budget),
    path("budgets/api/<str:budget_id>/delete", delete_budget),
    path("budgets/api/<str:budget_id>/line/update", update_line),
    path("budgets/api/<str:budget_id>/line/add", add_line),
    path("budgets/api/<str:budget_id>/line/delete", delete_lines),
    path("budgets/<str:budget_id>/report", report_page),
    path("budgets/<str:budget_id>", editor_page),
]
