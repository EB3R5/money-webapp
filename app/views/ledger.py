"""Ledger — the transaction Grid. Page render + a Grid datasource for AG Grid (Infinite
Row Model, lazy block loading over 14k+ rows). The block/row/update/delete dance lives in
app/grid.py over the transactions Store; this file declares the columns and keeps the
Category endpoint (picking a category rewrites Group + the other derived fields through
app/categorization.py). Rule apply, ML suggestions, and retrain live on the
categorization views."""

from django.urls import path

from .. import web
from ..categorization import apply_category, derived_for, ml_ready
from ..grid import Grid
from ..lookups import DERIVED_FIELDS
from ..store.categories import categories
from ..store.transactions import derive_month, transactions

# Columns surfaced in the grid (key = API key on the transactions store).
COLUMNS = ["Date", "Description", "Category", "Group", "Amount", "Account", "Institution"]
# Plainly editable columns. Category has its own endpoint (it derives Group/etc); Group
# is derived from Category, never typed directly.
EDITABLE = ["Date", "Description", "Amount", "Account", "Institution"]

grid = Grid(
    store=transactions,
    columns=COLUMNS,
    editable=EDITABLE,
    search_keys=["Description", "Category", "Account"],
    default_sort=[("Date", "desc")],
    derive=derive_month,              # Month follows an edited or added Date
)


def _ledger_enrich(doc, body):
    """Add-row hook: a chosen Category fills in Group + the other derived fields."""
    cat = (body.get("Category") or "").strip()
    if cat:
        doc["Category"] = cat
        doc.update(derived_for(cat))


def _categories():
    """Fixed category list, sorted by name: [{Category, Group, ...derived}] for the
    dropdown + client-side lookup."""
    rows = categories.list(order=[("Category", "asc")])
    return [{"Category": c["Category"], **{f: c.get(f) for f in DERIVED_FIELDS}}
            for c in rows if c.get("Category")]


@web.GET
def ledger_page(request):
    return web.page(request, "ledger.html",
                    {"total": transactions.count(), "columns": COLUMNS, "categories": _categories(),
                     "ml_ready": ml_ready()})


@web.POST
def update_category(request):
    """Inline edit from the grid. Body: {id, value}. Category is the only writable field;
    Group (and other derived fields) are looked up from the chosen category, not typed."""
    body = web.read_json(request)
    _id = body.get("id")
    value = (body.get("value") or "").strip()
    if not _id:
        return web.json({"ok": False, "error": "missing id"}, 400)
    if not value:
        # Never wipe a category to blank — an empty editor commit is a no-op.
        return web.json({"ok": False, "error": "empty category"}, 400)
    return web.json(apply_category(_id, value))


urlpatterns = [
    *grid.urlpatterns("transactions", enrich=_ledger_enrich),
    path("", ledger_page),
    path("api/transactions/category", update_category),
]
