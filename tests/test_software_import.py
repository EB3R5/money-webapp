import pytest
"""Import endpoint tests (ADR-0017): source_key idempotency, field ownership on
re-import, per-host location merge, the removal sweep scoped to the run's managers,
automatic-vs-manual Status, and the request contract. Seeds: s2 = pacman:ripgrep
installed on workstation with automatic status."""


from app.store.software import software
from tests import dbhelper


@pytest.fixture
def client(store_client):
    dbhelper.seed_software()
    return store_client


def entry(sk, name, manager, id_, version, host="workstation", **extra):
    return {"source_key": sk, "name": name, "kind": "cli", "version_installed": version,
            "install_locations": [{"host": host, "manager": manager, "id": id_, "version": version}],
            **extra}


def run(host="workstation", managers=("pacman", "aur", "npm"), entries=()):
    return {"host": host, "collected_at": "2026-09-30T18:00:00Z", "managers": list(managers),
            "entries": list(entries)}


RG = entry("pacman:ripgrep", "ripgrep", "pacman", "ripgrep", "14.1.1",
           description="A search tool", homepage="https://github.com/BurntSushi/ripgrep",
           license_id="MIT OR Unlicense", license_type="oss", kind="os_package")
FD = entry("pacman:fd", "fd", "pacman", "fd", "10.5.0-3", license_id="MIT", license_type="oss")
CLASP = entry("npm:@google/clasp", "@google/clasp", "npm", "@google/clasp", "3.4.1")


def by_key(sk):
    return software.one({"Source_Key": sk})


def test_import_adds_new_keys_with_sequential_ids_and_automatic_status(client):
    body = (client.post("/api/software/import", json=run(entries=[RG, FD, CLASP]))).json()
    assert body["status"] == "ok" and body["host"] == "workstation"
    # ripgrep exists (s2) but the run carries a description/homepage it lacks → updated, not added
    assert (body["added"], body["updated"], body["unchanged"], body["removed"]) == (2, 1, 0, 0)
    ids = {i["source_key"]: i for i in body["items"]}
    assert ids["pacman:fd"]["id"] == "SW-004" and ids["npm:@google/clasp"]["id"] == "SW-005"
    assert ids["pacman:ripgrep"]["action"] == "updated" and ids["pacman:ripgrep"]["id"] == "SW-002"
    fd = by_key("pacman:fd")
    assert fd["Status"] == "using" and fd["_import_status"] == "using" and fd["_src"] == "import"
    assert fd["Kind"] == "cli" and fd["License_Type"] == "oss" and fd["Currency"] == "USD"
    assert fd["Version_Installed"] == "10.5.0-3"
    assert fd["Install_Locations"] == [{"host": "workstation", "manager": "pacman", "id": "fd",
                                        "version": "10.5.0-3", "seen_at": "2026-09-30T18:00:00Z"}]
    assert fd["Link"] is None                                 # nothing to derive it from


def test_reimport_is_a_no_op(client):
    first = (client.post("/api/software/import", json=run(entries=[RG, FD]))).json()
    assert first["added"] == 1
    second = (client.post("/api/software/import", json=run(entries=[RG, FD]))).json()
    assert (second["added"], second["updated"], second["unchanged"], second["removed"]) == (0, 0, 2, 0)
    fd = by_key("pacman:fd")
    assert fd["_edited_at"] is None
    assert software.count({"Source_Key": "pacman:fd"}) == 1


def test_reimport_overwrites_facts_fills_blanks_keeps_curated(client):
    # User curated s2: renamed it, priced it, added notes, set a category.
    software.update("s2", {"Item_Name": "rg (ripgrep)", "Cost": 5.0, "Notes": "mine",
                                 "Category": "Tools", "Kind": "cli"})
    newer = dict(RG, version_installed="15.2.0", description="Newer text", kind="os_package",
                 category="Search", notes="import notes", cost=99, name="ripgrep",
                 install_locations=[{"host": "workstation", "manager": "pacman", "id": "ripgrep", "version": "15.2.0"}])
    body = (client.post("/api/software/import", json=run(entries=[newer]))).json()
    assert body["updated"] == 1
    doc = software.get("s2")
    assert doc["Version_Installed"] == "15.2.0"                         # OVERWRITE
    assert doc["Install_Locations"][0]["version"] == "15.2.0"
    assert doc["License_Id"] == "MIT OR Unlicense" and doc["Homepage"] == "https://github.com/BurntSushi/ripgrep"
    assert doc["Description"] == "Newer text"                           # FILL: s2 had none
    assert doc["Kind"] == "cli" and doc["Category"] == "Tools"          # FILL: already set → kept
    assert doc["Item_Name"] == "rg (ripgrep)" and doc["Cost"] == 5.0 and doc["Notes"] == "mine"   # curated
    assert doc["Stars"] == 50000                                        # not in the run → untouched


def test_missing_key_uninstalls_then_reinstall_restores(client):
    body = (client.post("/api/software/import", json=run(entries=[FD]))).json()   # no ripgrep this run
    assert body["removed"] == 1
    s2 = software.get("s2")
    assert s2["Status"] == "uninstalled" and s2["_import_status"] == "uninstalled"
    assert s2["Install_Locations"] == []
    body = (client.post("/api/software/import", json=run(entries=[FD, RG]))).json()
    assert body["updated"] == 1
    s2 = software.get("s2")
    assert s2["Status"] == "using" and len(s2["Install_Locations"]) == 1


def test_sweep_is_scoped_to_the_runs_managers(client):
    # An npm-only run must not touch pacman items.
    body = (client.post("/api/software/import", json=run(managers=["npm"], entries=[CLASP]))).json()
    assert body["added"] == 1 and body["removed"] == 0
    assert (software.get("s2"))["Status"] == "using"
    # An empty managers list never sweeps either.
    body = (client.post("/api/software/import", json=run(managers=[], entries=[]))).json()
    assert body["removed"] == 0


def test_manual_status_survives_import_and_sweep(client):
    software.update("s2", {"Status": "cancelled"})                                        # user took over
    body = (client.post("/api/software/import", json=run(entries=[FD]))).json()           # ripgrep absent
    assert body["removed"] == 1
    s2 = software.get("s2")
    assert s2["Status"] == "cancelled" and s2["Install_Locations"] == []
    client.post("/api/software/import", json=run(entries=[FD, RG]))                       # back again
    assert (software.get("s2"))["Status"] == "cancelled"


def test_second_host_merges_locations_and_keeps_the_first(client):
    mac_rg = entry("pacman:ripgrep", "ripgrep", "brew:formula", "ripgrep", "15.2.0", host="mac")
    body = (client.post("/api/software/import",
                              json=run(host="mac", managers=["brew:formula"], entries=[mac_rg]))).json()
    assert body["updated"] == 1 and body["removed"] == 0
    s2 = software.get("s2")
    assert sorted(l["host"] for l in s2["Install_Locations"]) == ["mac", "workstation"]
    # A later workstation run without ripgrep drops only workstation's location; still installed on mac.
    body = (client.post("/api/software/import", json=run(entries=[FD]))).json()
    s2 = software.get("s2")
    assert [l["host"] for l in s2["Install_Locations"]] == ["mac"] and s2["Status"] == "using"


def test_foreign_host_locations_in_an_entry_are_ignored(client):
    e = entry("cargo:x", "x", "cargo", "x", "1", host="elsewhere")
    body = (client.post("/api/software/import", json=run(managers=["cargo"], entries=[e]))).json()
    doc = by_key("cargo:x")
    assert body["added"] == 1 and doc["Install_Locations"] == [] and doc["Status"] == "trialing"


def test_status_hint_and_skipped_entries(client):
    e = {**entry("npm:y", "y", "npm", "y", "1"), "install_locations": [], "status": "installed_unused"}
    body = (client.post("/api/software/import",
                              json=run(managers=["npm"], entries=[e, {"name": "no key"}, "junk"]))).json()
    assert body["added"] == 1 and body["skipped"] == 2
    assert (by_key("npm:y"))["Status"] == "installed_unused"


def test_import_never_nulls_and_validates_body(client):
    e = dict(RG, description=None, license_id="")
    body = (client.post("/api/software/import", json=run(entries=[e]))).json()
    assert body["status"] == "ok"
    assert (software.get("s2"))["License_Id"] == "Unlicense"
    for bad in ([], {"host": ""}, {"host": "h"}, {"host": "h", "entries": {}, "managers": []},
                {"host": "h", "entries": [], "managers": "pacman"}):
        r = client.post("/api/software/import", json=bad)
        assert r.status_code == 400 and r.json()["status"] == "error"
    r = client.post("/api/software/import", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_import_route_is_not_swallowed_by_update(client):
    # /api/software/import is one segment past the slug; the importer must win over /{doc_id}.
    r = client.post("/api/software/import", json={"host": "h", "managers": [], "entries": []})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    from app.urls import VIEW_MODULES
    from app.views import software, software_sync
    from tests.dbhelper import routes
    assert "/api/software/import" in routes(software_sync)
    assert list(VIEW_MODULES).index(software_sync) < list(VIEW_MODULES).index(software)
