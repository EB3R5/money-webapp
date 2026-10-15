"""The one place a page module is registered. Order is match order: Django takes the first
pattern that fits, exactly as FastAPI took the first router, so fixed segments stay ahead of
`<str:doc_id>` routes. Adding a page means adding its module here."""

from .views import (account, accounts, activity, auth, balances, budgets, categories, categorization,
                    category_insights, clippers, credit, dashboard, data, documents, health_metrics, inventory,
                    inventory_clip, inventory_columns, inventory_export, investments, kits, ledger,
                    metrics, planning, reports, settings_feed, settings_users, simplefin, software,
                    software_clip, software_sync, tax)

# Fixed-segment routes one segment past a board's slug (/api/inventory/tree, /items,
# /taxonomy; /api/software/import, /items) must precede that board's /api/<slug>/<doc_id>.
VIEW_MODULES = (auth, account, ledger, categories, categorization,
                inventory_columns, inventory_clip, inventory_export, inventory,
                software_sync, software_clip, software, kits, documents, accounts,
                dashboard, category_insights, reports, planning, metrics, budgets,
                balances, investments, credit, tax, health_metrics, data, activity,
                simplefin, clippers, settings_feed, settings_users)

urlpatterns = [p for m in VIEW_MODULES for p in m.urlpatterns]
