import pytest
"""Software board tests through the real HTTP routes: the default/filtered views, the
group toggle, create (SW-### mint + defaults + Source_Key from Link), the `_meta`
overlay, the ↗ link, the facts route, duplicate-key vetoes, delete audit and route
registration. Pure derivations are covered in test_software_item.py."""

import html


from app.views.software import _software
from app.store.deletions import deletions
from app.store.software import software
from tests import dbhelper


@pytest.fixture
def sw_client(store_client):
    dbhelper.seed_software()
    return store_client


def test_default_view_groups_by_status_and_hides_uninstalled(sw_client):
    body = (sw_client.get("/software")).text
    assert "Obsidian Sync" in body and "ripgrep" in body
    assert "Old Editor" not in body                    # uninstalled hidden from the active view
    assert "<h2>using</h2>" in body


def test_board_total_is_monthly_subscription_cost(sw_client):
    body = (sw_client.get("/software")).text
    assert 'id="card-grand">$10<' in body             # s1 $10/mo; s2 is oss → contributes 0


def test_uninstalled_and_all_filters(sw_client):
    body = (sw_client.get("/software?status=uninstalled")).text
    assert "Old Editor" in body and "Obsidian Sync" not in body
    body = (sw_client.get("/software?status=all")).text
    assert "Old Editor" in body and "Obsidian Sync" in body


def test_group_toggle_by_kind_and_category(sw_client):
    body = (sw_client.get("/software")).text
    assert 'class="group-toggle"' in body and 'href="/software?group=status&status=active" class="active"' in body
    body = (sw_client.get("/software?group=kind")).text
    assert "<h2>saas</h2>" in body and "<h2>cli</h2>" in body
    body = (sw_client.get("/software?group=category")).text
    assert "<h2>Audio</h2>" in body and "<h2>Uncategorized</h2>" in body   # s2 has no category


def test_entries_sort_by_monthly_cost_then_name(sw_client):
    dbhelper.seed(software, [
        {"_id": "s4", "SW_ID": "SW-004", "Item_Name": "Aardvark Cloud", "Status": "using", "Kind": "saas",
         "License_Type": "subscription", "Billing_Cadence": "yearly", "Cost": 240.0},   # $20/mo
        {"_id": "s5", "SW_ID": "SW-005", "Item_Name": "Zed", "Status": "using", "Kind": "app"}])
    body = (sw_client.get("/software")).text
    i = {n: body.index(n) for n in ("Aardvark Cloud", "Obsidian Sync", "ripgrep", "Zed")}
    assert i["Aardvark Cloud"] < i["Obsidian Sync"] < i["ripgrep"] < i["Zed"]


def test_subtitle_hints_newer_version_from_meta(sw_client):
    body = html.unescape((sw_client.get("/software")).text)
    assert "v14.1.1 → v14.1.2" in body


def test_meta_overlay_embeds_stored_only_facts(sw_client):
    body = (sw_client.get("/software")).text
    assert '"install_locations"' in body and '"pacman:ripgrep"' in body
    assert '"stars": 50000' in body and '"automatic_status": true' in body


def test_link_icon_only_for_http_links(sw_client):
    body = (sw_client.get("/software?status=all")).text
    assert 'class="acct-link" href="https://obsidian.md/sync"' in body
    assert body.count('class="acct-link"') == 2                            # s1 + s2; s3 has no Link


def test_import_strip_and_nav_render(sw_client):
    body = (sw_client.get("/software")).text
    assert 'id="sw-import-file"' in body and 'id="sw-import-btn"' in body
    assert 'href="/software">Software</a>' in body
    assert 'id="card-search"' in body
    fields = body.split("searchFields: ", 1)[1].split("]", 1)[0]
    assert '"SW_ID"' in fields and '"Source_Key"' in fields and '"Link"' not in fields


def test_create_mints_sw_id_defaults_and_source_key(sw_client):
    r = sw_client.post("/api/software/row",
                             json={"Item_Name": "httpx", "Link": "https://pypi.org/project/httpx/", "Cost": "0"})
    data = r.json()
    assert data["ok"] and data["SW_ID"] == "SW-004"          # max existing (003) + 1
    doc = software.get(data["id"])
    assert doc["Status"] == "using" and doc["Kind"] == "app" and doc["Currency"] == "USD"
    assert doc["License_Type"] == "free" and doc["Billing_Cadence"] == "none" and doc["_src"] == "manual"
    assert doc["Source_Key"] == "pypi:httpx"                 # derived from the registry Link
    assert doc["Cost"] == 0.0 and doc["_import_status"] is None


def test_create_without_registry_link_has_no_source_key(sw_client):
    r = sw_client.post("/api/software/row", json={"Item_Name": "Some SaaS", "Link": "https://x.com/pricing"})
    doc = software.get(r.json()["id"])
    assert doc["Source_Key"] is None


def test_duplicate_source_key_is_refused_on_create_and_update(sw_client):
    r = sw_client.post("/api/software/row", json={"Item_Name": "rg again", "Source_Key": "pacman:ripgrep"})
    assert r.status_code == 400 and "SW-002" in r.json()["error"]
    assert software.count({"Source_Key": "pacman:ripgrep"}) == 1
    r = sw_client.post("/api/software/s1", json={"Source_Key": "pacman:ripgrep"})
    assert r.status_code == 400 and "SW-002" in r.json()["error"]
    r = sw_client.post("/api/software/s2", json={"Source_Key": "pacman:ripgrep", "Notes": "same key, own row"})
    assert r.status_code == 200 and r.json()["ok"]


def test_update_coerces_cost_and_leaves_stored_only_fields(sw_client):
    r = sw_client.post("/api/software/s2", json={"Cost": "$4.50", "Billing_Cadence": "monthly"})
    assert r.json()["ok"]
    doc = software.get("s2")
    assert doc["Cost"] == 4.5 and doc["Stars"] == 50000 and doc["Install_Locations"]


def test_facts_sets_remote_fields_only(sw_client):
    r = sw_client.post("/api/software/s2/facts", json={
        "name": "RIPGREP", "version_latest": "15.2.0", "stars": 68738, "topics": ["grep"],
        "license_id": "Unlicense", "description": "fast grep", "cost": 99, "notes": "hijack",
        "status": "cancelled", "source_key": "github:BurntSushi/ripgrep"})
    body = r.json()
    assert body["ok"] and set(body["updated"]) == {"Version_Latest", "Stars", "Topics", "Description"}
    doc = software.get("s2")
    assert doc["Version_Latest"] == "15.2.0" and doc["Description"] == "fast grep" and doc["Topics"] == ["grep"]
    assert doc["Item_Name"] == "ripgrep" and doc["Status"] == "using" and doc["Cost"] is None and doc["Notes"] is None
    assert doc["Source_Key"] == "pacman:ripgrep"            # an identity never silently changes
    assert doc["_refreshed_at"] is not None


def test_facts_fills_a_missing_source_key_and_refuses_a_taken_one(sw_client):
    r = sw_client.post("/api/software/s1/facts", json={"source_key": "pacman:ripgrep"})
    assert r.status_code == 400 and "SW-002" in r.json()["error"]
    r = sw_client.post("/api/software/s1/facts", json={"source_key": "github:obsidianmd/obsidian-releases",
                                                             "homepage": "https://obsidian.md"})
    assert r.json() == {"ok": True, "updated": ["Homepage", "Source_Key"]}
    assert (software.get("s1"))["Source_Key"] == "github:obsidianmd/obsidian-releases"
    assert (sw_client.post("/api/software/nope/facts", json={})).status_code == 404


def test_delete_audits_then_removes(sw_client):
    r = sw_client.post("/api/software/delete", json={"ids": ["s3"]})
    assert r.json() == {"ok": True, "deleted": 1}
    assert software.get("s3") is None
    logged = deletions.one({"collection": "software"})
    assert logged is not None and logged["doc"]["_id"] == "s3"


def test_routes_registered():
    from app.views import software as software_views
    from tests.dbhelper import routes
    paths = set(routes(_software.urlpatterns()))
    assert "/api/software/row" in paths and "/api/software/delete" in paths
    assert "/api/software/image/<str:file_id>" in paths and "/api/software/<str:doc_id>/documents" in paths
    assert "/api/software/<str:doc_id>/facts" in routes(software_views)
