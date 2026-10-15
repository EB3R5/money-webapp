"""Pure-function tests for the software schema module: the wire mapping, the monthly
cost derivation, subtitle/sort, source keys and the import status rule."""

from app.software_item import (FIELD_NAMES, STORED_ONLY, entry_sort_key, from_wire,
                               monthly_cost, split_source_key, source_key,
                               status_for_import, subtitle)


def test_stored_only_fields_are_not_form_fields():
    assert not set(STORED_ONLY) & set(FIELD_NAMES)


# --- from_wire ---------------------------------------------------------------

def test_from_wire_maps_and_drops_nulls():
    d = from_wire({"name": " ripgrep ", "vendor": None, "description": "", "kind": "CLI",
                   "cost": "$12.50", "stars": "14", "topics": ["grep", 1], "source_key": "pacman:ripgrep"})
    assert d == {"Item_Name": "ripgrep", "Kind": "cli", "Cost": 12.5, "Stars": 14,
                 "Topics": ["grep", "1"], "Source_Key": "pacman:ripgrep"}


def test_from_wire_drops_invalid_enums_and_bad_numbers():
    d = from_wire({"kind": "widget", "license_type": "oss", "billing_cadence": "weekly",
                   "cost": "n/a", "stars": "many"})
    assert d == {"License_Type": "oss"}


def test_from_wire_derives_link_from_homepage_then_repo():
    assert from_wire({"homepage": "https://h", "repo_url": "https://r"})["Link"] == "https://h"
    assert from_wire({"repo_url": "https://r"})["Link"] == "https://r"
    assert from_wire({"link": "https://l", "homepage": "https://h"})["Link"] == "https://l"
    assert "Link" not in from_wire({"name": "x"})


def test_from_wire_never_copies_status_or_locations():
    d = from_wire({"status": "using", "install_locations": [{"host": "x"}], "image_url": "https://i"})
    assert d == {}


# --- monthly cost ------------------------------------------------------------

def test_monthly_cost_per_cadence():
    assert monthly_cost({"Cost": 10.0, "Billing_Cadence": "monthly"}) == 10.0
    assert monthly_cost({"Cost": 120.0, "Billing_Cadence": "yearly"}) == 10.0
    assert monthly_cost({"Cost": 49.99, "Billing_Cadence": "one_time"}) is None
    assert monthly_cost({"Cost": 10.0, "Billing_Cadence": "none"}) is None
    assert monthly_cost({"Cost": 10.0}) is None
    assert monthly_cost({"Billing_Cadence": "monthly"}) is None


def test_monthly_cost_is_none_for_free_and_oss():
    assert monthly_cost({"Cost": 10.0, "Billing_Cadence": "monthly", "License_Type": "oss"}) is None
    assert monthly_cost({"Cost": 10.0, "Billing_Cadence": "monthly", "License_Type": "free"}) is None


# --- subtitle + sort ---------------------------------------------------------

def test_subtitle_shows_kind_cost_and_version_hint():
    assert subtitle({"Kind": "saas", "Cost": 10.0, "Billing_Cadence": "monthly"}) == "saas · $10/mo"
    assert subtitle({"Kind": "app", "Cost": 49.99, "Billing_Cadence": "one_time", "Version_Installed": "3.2"}) \
        == "app · $50 once · v3.2"
    assert subtitle({"Kind": "cli", "Version_Installed": "14.1.1", "Version_Latest": "14.1.2"}) \
        == "cli · v14.1.1 → v14.1.2"
    assert subtitle({"Version_Installed": "1.0", "Version_Latest": "1.0"}) == "v1.0"
    assert subtitle({}) is None


def test_entry_sort_highest_monthly_cost_first_then_name():
    a = {"Item_Name": "b", "Cost": 5.0, "Billing_Cadence": "monthly"}
    b = {"Item_Name": "a"}
    c = {"Item_Name": "c"}
    assert sorted([c, b, a], key=entry_sort_key) == [a, b, c]


# --- source keys -------------------------------------------------------------

def test_source_key_round_trips_scoped_and_nested_keys():
    assert split_source_key(source_key("npm", "@openai/codex")) == ("npm", "@openai/codex")
    assert split_source_key("brew:cask:visual-studio-code") == ("brew", "cask:visual-studio-code")
    assert split_source_key("github:BurntSushi/ripgrep") == ("github", "BurntSushi/ripgrep")
    assert split_source_key("nocolon") is None and split_source_key(None) is None
    assert split_source_key("pacman:") is None


# --- import status rule ------------------------------------------------------

def test_status_for_import_new_items():
    assert status_for_import(None, True) == "using"
    assert status_for_import(None, False) == "trialing"
    assert status_for_import(None, False, "installed_unused") == "installed_unused"
    assert status_for_import(None, False, "bogus") == "trialing"


def test_status_for_import_automatic_flips():
    auto = {"Status": "using", "_import_status": "using"}
    assert status_for_import(auto, False) == "uninstalled"
    assert status_for_import(auto, True) is None                       # still installed, no change
    gone = {"Status": "uninstalled", "_import_status": "uninstalled"}
    assert status_for_import(gone, True) == "using"                    # reinstalled
    assert status_for_import(gone, False) is None


def test_status_for_import_respects_manual_edits():
    manual = {"Status": "cancelled", "_import_status": "using"}
    assert status_for_import(manual, False) is None
    assert status_for_import(manual, True) is None
    clipped = {"Status": "trialing", "_import_status": None}
    assert status_for_import(clipped, True) is None


def test_norm_version_and_subtitle_ignore_pkgrel_and_v_prefix():
    from app.software_item import norm_version, same_version
    assert norm_version("15.2.0-1") == "15.2.0" and norm_version("v15.2.0") == "15.2.0"
    assert norm_version("1:2.3-4") == "2.3" and norm_version(None) is None
    assert same_version("15.2.0-1", "v15.2.0")
    assert subtitle({"Version_Installed": "15.2.0-1", "Version_Latest": "15.2.0"}) == "v15.2.0-1"
    assert subtitle({"Version_Installed": "15.1.0-2", "Version_Latest": "15.2.0"}) == "v15.1.0-2 → v15.2.0"
