"""CSRF, security headers, the error boundary, the body limit and the auth gate on Django
(app/middleware.py, config/settings.py), plus the vendoring that makes the strict CSP hold:
no third-party origin in any template, every inline <script>/<style> carries the request
nonce."""

import logging
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from app import security
from app.middleware import BodyLimitMiddleware
from tests import dbhelper
from tests.client import WebClient

TEMPLATES = sorted(Path("app/templates").glob("*.html"))
VENDOR = Path("app/static/vendor")


@pytest.fixture
def secure_client(store_db, settings):
    """Auth off, CSRF on."""
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = False
    return WebClient(enforce_csrf_checks=True)


@pytest.fixture
def gated_client(store_db, settings):
    """Auth on, CSRF off: the gate alone."""
    dbhelper.seed_ledger()
    settings.MONEY_AUTH_GATE = True
    return WebClient()


@pytest.fixture
def strict_client(store_db, settings):
    """Auth on, CSRF on: the real thing."""
    dbhelper.seed_ledger()
    get_user_model().objects.create_user("me", password="a-real-password-here")
    settings.MONEY_AUTH_GATE = True
    return WebClient(enforce_csrf_checks=True)


def _token_from(html: str) -> str:
    m = (re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
         or re.search(r'name="csrf-token" content="([^"]+)"', html))
    assert m, "no csrf token in page"
    return m.group(1)


# --- vendoring + nonces ------------------------------------------------------------------

def test_no_third_party_origins_in_templates_and_vendor_files_exist():
    for t in TEMPLATES:
        for line in t.read_text().splitlines():
            assert not re.search(r'(src|href)="https?://', line), f"{t.name}: {line.strip()}"
    for f in ("ag-grid-community.min.noStyle.js", "ag-grid.css", "ag-theme-quartz.css", "echarts.min.js", "html-to-image.min.js"):
        assert (VENDOR / f).stat().st_size > 10_000, f
    for css in ("ag-grid.css", "ag-theme-quartz.css"):
        assert not re.search(r"url\((?!['\"]?data:)", (VENDOR / css).read_text()), f"{css} loads an external url()"


def test_every_inline_script_and_style_carries_the_nonce_and_no_style_attributes():
    for t in TEMPLATES:
        s = t.read_text()
        for m in re.finditer(r"<(script|style)\b([^>]*)>", s):
            attrs = m.group(2)
            if m.group(1) == "script" and "src=" in attrs:
                continue
            assert 'nonce="{{ csp_nonce }}"' in attrs, f"{t.name}: <{m.group(1)}{attrs}>"
        assert not re.search(r'\sstyle="', s), f"{t.name} has an inline style attribute"
        # Inline event handlers never run under the nonce-only script-src: behaviour belongs
        # in a static script (ui.js for the page-wide ones).
        assert not re.search(r"\son[a-z]+=", s), f"{t.name} has an inline event handler"
    for js in Path("app/static/js").glob("*.js"):
        assert "style=" not in js.read_text(), f"{js.name} builds an inline style attribute"


def test_vendored_assets_are_served(secure_client):
    r = secure_client.get("/static/vendor/ag-grid-community.min.noStyle.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "cache-control" not in r.headers or r.headers["cache-control"] != "no-store"


# --- headers + error boundary -------------------------------------------------------------

def _assert_headers(r, *, nonce=None):
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "form-action 'self'" in csp
    script_src = re.search(r"script-src ([^;]+)", csp).group(1)
    assert script_src.startswith("'self' 'nonce-") and "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert "style-src 'self' 'unsafe-inline';" in csp             # AG Grid needs inline style attributes; a nonce here would void it
    if nonce:
        assert f"'nonce-{nonce}'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["x-frame-options"] == "DENY"
    assert "camera=()" in r.headers["permissions-policy"]


def test_headers_on_page_json_404_and_the_nonce_matches_the_markup(secure_client):
    r = secure_client.get("/")
    _assert_headers(r)
    nonce = re.search(r"'nonce-([^']+)'", r.headers["content-security-policy"]).group(1)
    assert f'<script nonce="{nonce}">' in r.text            # the page config block
    assert r.headers["cache-control"] == "no-store"
    r2 = secure_client.get("/api/transactions/doc/t1")
    assert r2.status_code == 200
    _assert_headers(r2); assert r2.headers["cache-control"] == "no-store"
    r3 = secure_client.get("/definitely/not/here")
    assert r3.status_code == 404 and "text/html" in r3.headers["content-type"]; _assert_headers(r3)
    assert secure_client.get("/api/definitely/not/here").status_code == 404
    r4 = secure_client.get("/static/css/app.css")
    assert r4.status_code == 200 and r4.headers.get("cache-control") != "no-store"
    _assert_headers(r4)
    # a fresh nonce per request
    assert nonce != re.search(r"'nonce-([^']+)'", secure_client.get("/").headers["content-security-policy"]).group(1)


def test_forced_500_renders_the_error_page_without_a_traceback(secure_client, settings, caplog):
    settings.ROOT_URLCONF = "tests.urls_extra"
    with caplog.at_level(logging.ERROR, logger="money.security"):
        r = secure_client.get("/__boom")
    assert r.status_code == 500 and "text/html" in r.headers["content-type"]
    _assert_headers(r)
    assert "Something went wrong" in r.text
    assert "Traceback" not in r.text and "RuntimeError" not in r.text and "secret detail" not in r.text
    assert any("unhandled error" in rec.getMessage() for rec in caplog.records)
    assert not any("u:p@" in (rec.exc_text or "") for rec in caplog.records)   # redacted in the log too


def test_a_failed_request_rolls_the_store_back(store_client, settings):
    """A view that wrote to the store and then raised leaves no row behind (the FastAPI
    gate let the exception propagate out of the scope; Django answers it inside)."""
    from app.store.transactions import transactions
    settings.ROOT_URLCONF = "tests.urls_extra"
    settings.MONEY_AUTH_GATE = False
    r = store_client.post("/__boom_after_write", json={})
    assert r.status_code == 500
    assert dbhelper.get(transactions, "boom") is None


def test_hsts_only_behind_https(secure_client, monkeypatch):
    assert "strict-transport-security" not in secure_client.get("/healthz").headers
    monkeypatch.setattr(security, "SESSION_HTTPS_ONLY", True)
    assert secure_client.get("/healthz").headers["strict-transport-security"].startswith("max-age=")


def test_docs_are_off(secure_client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert secure_client.get(path).status_code == 404


# --- body limit ------------------------------------------------------------------------

def test_body_over_64k_is_413(store_client):
    big = b'{"id":"t1","field":"Amount","value":"' + b"9" * (65 * 1024) + b'"}'
    r = store_client.post("/api/transactions/update", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    small = store_client.post("/api/transactions/update", json={"id": "t1", "field": "Amount", "value": "1"})
    assert small.status_code == 200


def test_chunked_body_is_411_and_an_empty_post_passes():
    """WSGI cannot count a chunked body as it streams: a request that declares a transfer
    encoding and no length is refused up front; one with neither has no body."""
    from django.http import HttpResponse
    mw = BodyLimitMiddleware(lambda request: HttpResponse("ok"))
    req = RequestFactory().post("/api/transactions/update", data=b"{}", content_type="application/json",
                                headers={"Transfer-Encoding": "chunked"})
    del req.META["CONTENT_LENGTH"]
    assert mw(req).status_code == 411
    empty = RequestFactory().post("/logout")
    empty.META.pop("CONTENT_LENGTH", None)
    assert mw(empty).status_code == 200


def test_multipart_gets_the_upload_limit(store_client):
    payload = b"a" * (200 * 1024)
    r = store_client.post("/api/transactions/update", files={"png": ("x.png", payload, "image/png")})
    assert r.status_code != 413                          # 200 KiB multipart is fine (it fails later, as bad input)


# --- CSRF ------------------------------------------------------------------------------

def test_post_without_token_is_403_with_header_or_field_passes(secure_client):
    r = secure_client.post("/api/transactions/category", json={"id": "t2", "value": "Auto"})
    assert r.status_code == 403 and r.json()["ok"] is False
    token = _token_from(secure_client.get("/").text)              # mints it into the session
    r = secure_client.post("/api/transactions/category", json={"id": "t2", "value": "Auto"},
                           headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.json()["ok"]
    r = secure_client.post("/api/transactions/category", json={"id": "t2", "value": "Auto"},
                           headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    r = secure_client.post("/logout", data={"csrfmiddlewaretoken": token})    # form field
    assert r.status_code == 303
    r = secure_client.post("/logout", data={})
    assert r.status_code == 403 and "text/html" in r.headers["content-type"]


def test_cross_site_fetch_metadata_is_rejected(secure_client):
    token = _token_from(secure_client.get("/").text)
    ok = {"X-CSRF-Token": token, "Sec-Fetch-Site": "same-origin"}
    assert secure_client.post("/api/transactions/category", json={"id": "t2", "value": "Auto"}, headers=ok).status_code == 200
    bad = {"X-CSRF-Token": token, "Sec-Fetch-Site": "cross-site"}
    assert secure_client.post("/api/transactions/category", json={"id": "t2", "value": "Auto"}, headers=bad).status_code == 403
    none = {"X-CSRF-Token": token, "Sec-Fetch-Site": "none"}
    assert secure_client.post("/api/transactions/category", json={"id": "t2", "value": "Auto"}, headers=none).status_code == 200


def test_get_and_exempt_paths_need_no_token(secure_client):
    assert secure_client.get("/api/transactions/doc/t1").status_code == 200
    assert secure_client.get("/healthz").status_code == 200


def test_login_form_carries_the_token_and_the_real_flow_works(strict_client):
    page = strict_client.get("/login")
    token = _token_from(page.text)
    r = strict_client.post("/login", data={"username": "me", "password": "a-real-password-here"})
    assert r.status_code == 403                                             # no token → rejected before auth
    r = strict_client.post("/login", data={"username": "me", "password": "a-real-password-here", "csrfmiddlewaretoken": token})
    assert r.status_code == 303 and r.headers["location"] == "/"
    home = strict_client.get("/")
    assert home.status_code == 200 and 'name="csrf-token"' in home.text and "csrf.js" in home.text
    # the session was regenerated on login; the page carries the new token and it works
    new_token = _token_from(home.text)
    assert strict_client.post("/logout", data={"csrfmiddlewaretoken": new_token}).status_code == 303


def test_document_text_paths_get_the_upload_limit(store_client):
    big = b'{"body":"' + b"x" * (100 * 1024) + b'"}'
    r = store_client.post("/api/documents/render", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 200
    r2 = store_client.post("/api/transactions/update", content=big, headers={"content-type": "application/json"})
    assert r2.status_code == 413


def test_a_route_may_own_its_frame_headers_but_nothing_else(store_client, settings):
    settings.ROOT_URLCONF = "tests.urls_extra"
    r = store_client.get("/_test/framed")
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["x-content-type-options"] == "nosniff"            # still stamped
    assert r.headers["cache-control"] == "no-store"                    # not route-owned
    assert security.response_headers("n", "/")[0][0] == "Content-Security-Policy"


# --- auth gate -------------------------------------------------------------------------

def test_gate_redirects_pages_401s_api_and_lets_exempt_paths_through(gated_client):
    r = gated_client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = gated_client.get("/api/transactions/doc/t1")
    assert r.status_code == 401 and r.json() == {"detail": "Not authenticated"}
    assert gated_client.get("/healthz").status_code == 200
    assert gated_client.get("/static/css/app.css").status_code == 200
    assert gated_client.get("/api/transactions/doc/t1", headers={"Authorization": "Bearer anything"}).status_code == 401


def test_a_signed_in_user_passes_the_gate(gated_client):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.create_user("me", password="a-long-enough-password")
    gated_client.django.force_login(user)
    assert gated_client.get("/").status_code == 200
    assert gated_client.post("/logout").status_code == 303
    assert gated_client.get("/").status_code == 303


# --- the browser behind HTTPS -------------------------------------------------------------

def test_login_post_over_https_passes_with_the_browsers_origin_and_fails_with_null(strict_client):
    """Behind `tailscale serve` the request is secure, and Django's CSRF check then needs
    the browser's Origin (or Referer) to match the site. A browser sends `Origin: null` on
    POSTs when the page's Referrer-Policy is no-referrer — which is why the policy is
    same-origin (app/security.py)."""
    token = _token_from(strict_client.get("/login", secure=True).text)
    ok = strict_client.post("/login", data={"username": "me", "password": "a-real-password-here",
                                            "csrfmiddlewaretoken": token},
                            secure=True, headers={"Origin": "https://testserver"})
    assert ok.status_code == 303 and ok.headers["location"] == "/"
    strict_client.post("/logout", data={"csrfmiddlewaretoken": _token_from(strict_client.get("/", secure=True).text)}, secure=True,
                       headers={"Origin": "https://testserver"})
    token = _token_from(strict_client.get("/login", secure=True).text)
    null = strict_client.post("/login", data={"username": "me", "password": "a-real-password-here",
                                              "csrfmiddlewaretoken": token},
                              secure=True, headers={"Origin": "null"})
    assert null.status_code == 403


def test_referrer_policy_keeps_the_origin_for_our_own_posts(secure_client):
    assert secure_client.get("/login").headers["referrer-policy"] == "same-origin"


def test_multipart_outside_the_api_keeps_the_small_limit(store_client):
    """The upload allowance is for API routes (photos, documents, the bundle); the login form
    — reachable by anyone — stays at 64 KiB whatever content type the request claims."""
    payload = b"a" * (200 * 1024)
    r = store_client.post("/login", files={"x": ("x.png", payload, "image/png")})
    assert r.status_code == 413
    r = store_client.post("/setup", files={"x": ("x.png", payload, "image/png")})
    assert r.status_code == 413
