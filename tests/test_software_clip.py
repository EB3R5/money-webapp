"""Software clipper, the pure half: the URL router and the registry mappers against
recorded responses (tests/fixtures/software/), the payload mapper for what the
bookmarklet harvests off a generic page, and the httpx shell through a MockTransport
(routing, token header, 404 tolerance, network failure → None). The routes are in
test_software_clip_routes.py."""

import json
from pathlib import Path

import httpx
import pytest

from app.software_clip import (clean_title, fetch_by_source_key, fetchable, fields_from_brew,
                               fields_from_github, fields_from_itunes, fields_from_npm,
                               fields_from_payload, fields_from_pypi, github_repo_from_url, route)

FIX = Path(__file__).parent / "fixtures" / "software"


def fx(name):
    return json.loads((FIX / name).read_text())


# --- route -------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/BurntSushi/ripgrep", ("github", "BurntSushi/ripgrep")),
    ("https://github.com/BurntSushi/ripgrep/tree/master/crates", ("github", "BurntSushi/ripgrep")),
    ("https://github.com/BurntSushi/ripgrep.git", ("github", "BurntSushi/ripgrep")),
    ("https://www.github.com/o/r?tab=readme", ("github", "o/r")),
    ("https://github.com/topics/cli", None),
    ("https://github.com/BurntSushi", None),
    ("https://pypi.org/project/httpx/", ("pypi", "httpx")),
    ("https://pypi.org/project/httpx/0.28.1/", ("pypi", "httpx")),
    ("https://www.npmjs.com/package/express", ("npm", "express")),
    ("https://www.npmjs.com/package/@openai/codex/v/0.1.0", ("npm", "@openai/codex")),
    ("https://apps.apple.com/us/app/things-3/id904280696?mt=12", ("appstore", "904280696")),
    ("https://apps.apple.com/de/app/id904280696", ("appstore", "904280696")),
    ("https://formulae.brew.sh/cask/visual-studio-code", ("brew", "cask:visual-studio-code")),
    ("https://formulae.brew.sh/formula/ripgrep.html", ("brew", "formula:ripgrep")),
    ("https://marketplace.visualstudio.com/items?itemName=ms-python.python", ("vscode", "ms-python.python")),
    ("https://obsidian.md/pricing", None),
    ("not a url", None),
])
def test_route(url, expected):
    assert route(url) == expected


def test_fetchable_sources():
    assert fetchable("github") and fetchable("brew")
    assert not fetchable("pacman") and not fetchable("vscode") and not fetchable("")


def test_github_repo_from_url():
    assert github_repo_from_url("https://github.com/encode/httpx/blob/master/x") == "encode/httpx"
    assert github_repo_from_url("https://www.python-httpx.org") is None
    assert github_repo_from_url(None) is None


def test_clean_title():
    assert clean_title("GitHub - BurntSushi/ripgrep: ripgrep recursively searches") == "ripgrep recursively searches"
    assert clean_title("Obsidian - Sharpen your thinking") == "Obsidian - Sharpen your thinking"
    assert clean_title("") is None


# --- mappers on recorded JSON ------------------------------------------------

def test_fields_from_github():
    f = fields_from_github(fx("github_repo.json"), fx("github_release.json"))
    assert f["name"] == "ripgrep" and f["vendor"] == "BurntSushi"
    assert f["repo_url"] == "https://github.com/BurntSushi/ripgrep"
    assert f["homepage"] == "https://github.com/BurntSushi/ripgrep"      # empty homepage → html_url
    assert f["license_id"] == "Unlicense" and f["license_type"] == "oss"
    assert f["stars"] == 68738 and "grep" in f["topics"] and f["archived"] is False
    assert f["version_latest"] == "15.2.0" and f["kind"] == "library"
    assert f["image_url"].startswith("https://avatars.githubusercontent.com/")
    assert "version_latest" not in fields_from_github(fx("github_repo.json"))


def test_fields_from_github_skips_noassertion_license():
    repo = {**fx("github_repo.json"), "license": {"spdx_id": "NOASSERTION"}}
    f = fields_from_github(repo)
    assert "license_id" not in f and "license_type" not in f


def test_fields_from_pypi():
    f = fields_from_pypi(fx("pypi.json"))
    assert f["name"] == "httpx" and f["version_latest"] == "0.28.1"
    assert f["description"] == "The next generation HTTP client."
    assert f["license_id"] == "BSD-3-Clause" and f["license_type"] == "oss"
    assert f["repo_url"] == "https://github.com/encode/httpx"
    assert f["homepage"] == "https://github.com/encode/httpx" and f["kind"] == "library"
    assert "vendor" not in f                                             # author null


def test_fields_from_npm_scoped():
    f = fields_from_npm(fx("npm_scoped.json"))
    assert f["name"] == "@openai/codex" and f["version_latest"] == "0.159.2"   # dist-tags.latest, not beta
    assert f["repo_url"] == "https://github.com/openai/codex"                 # git+….git stripped
    assert f["license_id"] == "Apache-2.0" and f["vendor"] == "openai-publisher"


def test_fields_from_itunes_paid_app():
    f = fields_from_itunes(fx("itunes.json"))
    assert f["name"] == "Things 3" and f["vendor"].startswith("Cultured Code")
    assert f["cost"] == 49.99 and f["currency"] == "USD"
    assert f["billing_cadence"] == "one_time" and f["license_type"] == "perpetual"
    assert f["bundle_id"] == "com.culturedcode.ThingsMac" and f["version_latest"] == "3.24.1"
    assert f["category"] == "Productivity" and f["kind"] == "app"
    assert f["image_url"].endswith("512x512bb.png") and f["link"].startswith("https://apps.apple.com/")


def test_fields_from_itunes_free_and_empty():
    j = fx("itunes.json")
    j["results"][0]["price"] = 0
    f = fields_from_itunes(j)
    assert f["license_type"] == "free" and "cost" not in f and "billing_cadence" not in f
    assert fields_from_itunes({"resultCount": 0, "results": []}) == {}


def test_fields_from_brew():
    cask = fields_from_brew(fx("brew_cask.json"), "cask")
    assert cask["name"] == "Microsoft Visual Studio Code" and cask["kind"] == "app"
    assert cask["version_latest"] == "1.140.0" and cask["homepage"] == "https://code.visualstudio.com/"
    formula = fields_from_brew(fx("brew_formula.json"), "formula")
    assert formula["name"] == "ripgrep" and formula["kind"] == "cli"
    assert formula["license_id"] == "Unlicense" and formula["version_latest"] == "15.2.0"
    assert formula["repo_url"] == "https://github.com/BurntSushi/ripgrep"


# --- the generic page, as the bookmarklet harvested it -------------------------

SKETCH = {
    "url": "https://www.sketch.com/pricing/", "title": "Sketch · Pricing",
    "og_title": "Sketch pricing", "og_description": "Design, prototype, collaborate.",
    "og_image": "/social.png",
    "ld_app": {"@type": "SoftwareApplication", "name": "Sketch", "applicationCategory": "DesignApplication",
               "softwareVersion": "2026.3.1", "author": {"@type": "Organization", "name": "Sketch B.V."},
               "offers": {"@type": "Offer", "price": "12", "priceCurrency": "USD"}},
}


def test_fields_from_payload_prefers_software_application_ld():
    f = fields_from_payload(SKETCH)
    assert f["name"] == "Sketch" and f["vendor"] == "Sketch B.V."
    assert f["category"] == "DesignApplication" and f["version_latest"] == "2026.3.1"
    assert f["cost"] == "12" and f["currency"] == "USD" and f["billing_cadence"] == "one_time"
    assert f["image_url"] == "https://www.sketch.com/social.png"
    assert f["description"] == "Design, prototype, collaborate."
    assert f["link"] == "https://www.sketch.com/pricing/"


def test_fields_from_payload_og_only_and_github_title_cleanup():
    f = fields_from_payload({"url": "https://github.com/Homebrew/brew", "ld_app": None,
                             "og_title": "GitHub - Homebrew/brew: 🍺 The Package Manager",
                             "og_image": "https://opengraph.githubassets.com/x", "og_description": ""})
    assert f["name"] == "🍺 The Package Manager"
    assert f["image_url"] == "https://opengraph.githubassets.com/x"
    assert "description" not in f and "cost" not in f
    assert fields_from_payload({"url": "https://x.example/", "title": "Just a title"})["name"] == "Just a title"
    assert fields_from_payload({}) == {} and fields_from_payload("junk") == {}


def test_fields_from_payload_offers_list_and_free_price():
    p = {**SKETCH, "ld_app": {**SKETCH["ld_app"], "offers": [{"price": 0, "priceCurrency": "USD"}]}}
    f = fields_from_payload(p)
    assert "cost" not in f and "billing_cadence" not in f and "currency" not in f


# --- the shell via MockTransport ---------------------------------------------

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_by_source_key_github_with_release_and_token(monkeypatch):
    monkeypatch.setattr("app.software_clip.GITHUB_TOKEN", "tok123")
    seen = {}

    def handler(req):
        seen[req.url.path] = req.headers.get("authorization")
        if req.url.path == "/repos/BurntSushi/ripgrep":
            return httpx.Response(200, json=fx("github_repo.json"))
        if req.url.path == "/repos/BurntSushi/ripgrep/releases/latest":
            return httpx.Response(200, json=fx("github_release.json"))
        return httpx.Response(404)

    got = fetch_by_source_key("github:BurntSushi/ripgrep", client=_client(handler))
    assert got["fields"]["version_latest"] == "15.2.0" and got["fields"]["stars"] == 68738
    assert got["image_url"].startswith("https://avatars.")
    assert "image_url" not in got["fields"]
    assert seen["/repos/BurntSushi/ripgrep"] == "Bearer tok123"


def test_fetch_by_source_key_github_tolerates_missing_release(monkeypatch):
    monkeypatch.setattr("app.software_clip.GITHUB_TOKEN", "")

    def handler(req):
        if req.url.path.endswith("/releases/latest"):
            return httpx.Response(404, json={"message": "Not Found"})
        assert "authorization" not in req.headers
        return httpx.Response(200, json=fx("github_repo.json"))

    got = fetch_by_source_key("github:BurntSushi/ripgrep", client=_client(handler))
    assert got["fields"]["name"] == "ripgrep" and "version_latest" not in got["fields"]


def test_fetch_by_source_key_other_registries():
    def handler(req):
        table = {"pypi.org": "pypi.json", "registry.npmjs.org": "npm_scoped.json",
                 "itunes.apple.com": "itunes.json", "formulae.brew.sh": "brew_cask.json"}
        return httpx.Response(200, json=fx(table[req.url.host]))

    c = _client(handler)
    assert fetch_by_source_key("pypi:httpx", client=c)["fields"]["version_latest"] == "0.28.1"
    assert fetch_by_source_key("npm:@openai/codex", client=c)["fields"]["name"] == "@openai/codex"
    assert fetch_by_source_key("appstore:904280696", client=c)["fields"]["bundle_id"] == "com.culturedcode.ThingsMac"
    assert fetch_by_source_key("brew:cask:visual-studio-code", client=c)["fields"]["kind"] == "app"


def test_fetch_by_source_key_local_bad_and_failing():
    def boom(req):
        raise httpx.ConnectError("down")

    assert fetch_by_source_key("pacman:ripgrep") is None
    assert fetch_by_source_key("vscode:ms-python.python") is None
    assert fetch_by_source_key("nonsense") is None
    assert fetch_by_source_key("brew:bogus:x", client=_client(boom)) is None
    assert fetch_by_source_key("pypi:httpx", client=_client(boom)) is None
    assert fetch_by_source_key("pypi:nope", client=_client(lambda r: httpx.Response(404))) is None


# --- bookmarklet -------------------------------------------------------------

def test_software_bookmarklet_shape():
    from app.software_clip import software_bookmarklet
    js = software_bookmarklet("http://127.0.0.1:8010/")
    assert js.startswith("javascript:(function(){")
    assert "\n" not in js and '"' not in js
    assert "'127.0.0.1:8010'" in js                          # self-guard host
    assert "http://127.0.0.1:8010/software/clip#" in js      # popup target
    assert "'money-clip-software'" in js                     # its own popup window
    assert "SoftwareApplication" in js and "og:title" in js and "og:description" in js
