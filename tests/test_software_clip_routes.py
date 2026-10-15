import pytest
"""Software clipper routes: the shared popup (window.CLIP + its image-friendly CSP),
prepare (registry facts win, harvested fields fill, match by Source_Key then by
normalised Link, generic pages), the picker, fetch-image, and registration order."""


from app.store.software import software
from tests import dbhelper


@pytest.fixture
def sw_client(store_client):
    dbhelper.seed_software()
    return store_client


GH_FIELDS = {"name": "ripgrep", "vendor": "BurntSushi", "description": "recursively searches",
             "homepage": "https://github.com/BurntSushi/ripgrep", "repo_url": "https://github.com/BurntSushi/ripgrep",
             "license_id": "Unlicense", "license_type": "oss", "stars": 68738, "topics": ["grep", "rust"],
             "archived": False, "version_latest": "15.2.0", "kind": "library"}


def gh_info(sk):
    assert sk == "github:BurntSushi/ripgrep"
    return {"fields": dict(GH_FIELDS), "image_url": "https://avatars.githubusercontent.com/u/1?v=4"}


def test_popup_renders_window_clip_with_its_own_csp(sw_client):
    r = sw_client.get("/software/clip")
    assert r.status_code == 200 and "clip-table" in r.text
    assert '"slug": "software"' in r.text and '"factsRoute": true' in r.text and "/static/js/clip.js" in r.text
    assert "img-src 'self' data: blob: https:;" in r.headers["content-security-policy"]
    assert "script-src 'self' 'nonce-" in r.headers["content-security-policy"]
    r = sw_client.get("/inventory/clip")
    assert '"slug": "inventory"' in r.text and '"factsRoute": false' in r.text
    assert "img-src 'self' data: blob: https:;" in r.headers["content-security-policy"]
    assert "https:" not in (sw_client.get("/software")).headers["content-security-policy"]


def test_prepare_registry_facts_win_and_match_by_source_key(sw_client, monkeypatch):
    monkeypatch.setattr("app.views.software_clip.fetch_by_source_key", gh_info)
    body = {"url": "https://github.com/BurntSushi/ripgrep#readme", "title": "GitHub - BurntSushi/ripgrep: x",
            "og_title": "GitHub - BurntSushi/ripgrep: harvested", "og_image": "https://opengraph.githubassets.com/x",
            "og_description": "harvested desc", "ld_app": None}
    d = (sw_client.post("/api/software/clip/prepare", json=body)).json()
    assert d["ok"] and d["source_key"] == "github:BurntSushi/ripgrep"
    assert d["scraped"]["Item_Name"] == "ripgrep" and d["scraped"]["Vendor"] == "BurntSushi"
    assert d["scraped"]["Description"] == "recursively searches"                 # registry over harvested
    assert d["scraped"]["Link"] == body["url"] and d["scraped"]["Kind"] == "library"
    assert d["scraped"]["Source_Key"] == "github:BurntSushi/ripgrep" and d["scraped"]["License_Type"] == "oss"
    assert d["facts"]["stars"] == 68738 and d["facts"]["version_latest"] == "15.2.0"
    assert d["facts"]["source_key"] == "github:BurntSushi/ripgrep" and "name" not in d["facts"]
    assert d["images"][0].startswith("https://avatars.") and "https://opengraph.githubassets.com/x" in d["images"]
    # s2 is pacman:ripgrep, not github:… → no key match; its Link is the repo page → link match
    assert d["match"]["_id"] == "s2" and d["match_count"] == 1 and d["link_same"]
    assert d["categories"] == [{"_id": "Audio", "Group": ""}]


def test_prepare_matches_source_key_before_link(sw_client, monkeypatch):
    monkeypatch.setattr("app.views.software_clip.fetch_by_source_key", lambda sk: None)
    software.update("s1", {"Source_Key": "github:obsidianmd/obsidian-releases"})
    d = (sw_client.post("/api/software/clip/prepare",
                              json={"url": "https://github.com/obsidianmd/obsidian-releases?tab=readme"})).json()
    assert d["ok"] and d["match"]["_id"] == "s1" and not d["link_same"]      # s1's Link is obsidian.md/sync
    assert d["scraped"]["Source_Key"] == "github:obsidianmd/obsidian-releases"
    assert "Item_Name" not in d["scraped"]                                        # registry down, nothing harvested


def test_prepare_generic_page_uses_harvested_fields(sw_client):
    body = {"url": "https://www.sketch.com/pricing/?utm_source=x", "title": "Sketch · Pricing",
            "og_title": "Sketch pricing", "og_description": "Design, prototype.", "og_image": "/social.png",
            "ld_app": {"name": "Sketch", "applicationCategory": "DesignApplication", "softwareVersion": "2026.3.1",
                       "author": "Sketch B.V.", "offers": {"price": "12", "priceCurrency": "USD"}}}
    d = (sw_client.post("/api/software/clip/prepare", json=body)).json()
    assert d["ok"] and d["source_key"] is None and d["match"] is None and d["match_count"] == 0
    assert d["scraped"]["Item_Name"] == "Sketch" and d["scraped"]["Vendor"] == "Sketch B.V."
    assert d["scraped"]["Cost"] == 12.0 and d["scraped"]["Billing_Cadence"] == "one_time"
    assert d["scraped"]["Link"] == body["url"] and d["category"]["suggested"] == "DesignApplication"
    assert d["facts"] == {"version_latest": "2026.3.1", "currency": "USD"}
    assert d["images"] == ["https://www.sketch.com/social.png"]
    r = sw_client.post("/api/software/clip/prepare", json={"url": "ftp://nope"})
    assert r.status_code == 400 and "URL" in r.json()["error"]


def test_picker_searches_software_fields(sw_client):
    d = (sw_client.get("/api/software/items?q=pacman")).json()
    assert [i["SW_ID"] for i in d["items"]] == ["SW-002"]                 # Source_Key is searchable
    assert (sw_client.get("/api/software/items?q=")).json() == {"items": []}
    d = (sw_client.get("/api/software/items?q=obsidian")).json()
    assert d["items"][0]["Item_Name"] == "Obsidian Sync" and d["items"][0]["Vendor"] == "Obsidian"


def test_fetch_image_attaches_to_software(sw_client, monkeypatch):
    monkeypatch.setattr("app.views.inventory_clip.download_image",
                        lambda url, referer=None: {"ok": True, "data": b"\x89PNG", "content_type": "image/png",
                                                   "filename": "rg.png"})
    r = sw_client.post("/api/software/s2/fetch-image", json={"image_urls": ["https://x/rg.png"]})
    assert r.json()["ok"] and r.json()["attached"] == 1
    doc = software.get("s2")
    assert len(doc["_images"]) == 1 and doc["_images"][0]["content_type"] == "image/png"
    img = sw_client.get("/api/software/image/" + doc["_images"][0]["id"])
    assert img.status_code == 200 and img.content == b"\x89PNG"
    r = sw_client.post("/api/software/nope/fetch-image", json={"image_urls": ["https://x/y.png"]})
    assert r.status_code == 404


def test_routes_registered_before_the_board():
    from app.urls import VIEW_MODULES
    from app.views import software, software_clip, software_sync
    from tests.dbhelper import routes
    mods = list(VIEW_MODULES)
    assert mods.index(software_clip) < mods.index(software) and mods.index(software_sync) < mods.index(software)
    paths = set(routes(software_clip))
    assert "/api/software/clip/prepare" in paths and "/api/software/items" in paths
    assert "/api/software/<str:doc_id>/fetch-image" in paths and "/software/clip" in paths
