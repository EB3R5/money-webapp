"""Documents (app/documents.py, routers/documents.py, the CardCollection panel, ADR-0016):
the text-inline / Blob rule, sanitized Markdown, download-only files, dirty-diff
edits, tolerant delete, the item delete cascade, and the document page by kind."""

import pytest

from app import documents
from app.views.accounts import _accounts
from app.views import documents as documents_views
from app.views.inventory import _inventory
from app.store.blobs import blobs
from app.store.deletions import deletions
from app.store.documents import documents as store
from app.web import DomainError
from tests import dbhelper


@pytest.fixture
def doc_client(store_client):
    """Inventory seeded (inv1 Drill, inv2 Pen) plus one Markdown document on inv2."""
    dbhelper.seed_inventory()
    store.insert({"_id": "d1", "parent_table": "inventory", "parent_id": "inv2",
                        "name": "repro.md", "kind": "md", "content_type": "text/markdown",
                        "size": 8, "body": "# Repro\n"})
    return store_client


def _upload(client, parent, *files_):
    r = client.post(f"/api/inventory/{parent}/documents", files=[("files", f) for f in files_])
    return r.json()


# --- pure rules -----------------------------------------------------------------------

def test_classify_by_extension_then_content_type():
    assert documents.classify("notes.md") == "md"
    assert documents.classify("Notes.MARKDOWN") == "md"
    assert documents.classify("readme.txt") == "txt"
    assert documents.classify("Page.HTM") == "file"
    assert documents.classify("page.html", "text/html") == "file"
    assert documents.classify("photo.jpg", "image/jpeg") == "file"
    assert documents.classify("blob", "text/markdown; charset=utf-8") == "md"
    assert documents.classify("scan.pdf", "application/pdf") == "file"


def test_render_markdown_strips_scripts_keeps_structure():
    html = documents.render_markdown(
        "# Hi\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>alert(1)</script>\n\n"
        "**bold** <a href=\"javascript:alert(2)\" onclick=\"x()\">l</a>")
    assert "<h1>Hi</h1>" in html and "<table>" in html and "<strong>bold</strong>" in html
    assert "<script" not in html and "onclick" not in html and "javascript:" not in html


def test_render_text_escapes_markup():
    html = documents.render_text("<b>x</b> & y")
    assert html == '<pre class="doc-plain">&lt;b&gt;x&lt;/b&gt; &amp; y</pre>'


# --- uploads and notes ------------------------------------------------------------------

def test_upload_text_inline_and_binary_as_blob(doc_client, store_db):
    d = _upload(doc_client, "inv1",
                      ("plan.md", b"# Plan\n\n- one", "text/markdown"),
                      ("shot.png", b"\x89PNG....", "image/png"))
    assert d["ok"] and len(d["documents"]) == 2 and d["errors"] == []
    md = store.one({"name": "plan.md"})
    assert md["kind"] == "md" and md["body"].startswith("# Plan") and md["file_ext"] is None
    assert md["parent_table"] == "inventory" and md["parent_id"] == "inv1"
    png = store.one({"name": "shot.png"})
    assert png["kind"] == "file" and png["body"] is None and png["file_ext"] == "png"
    assert blobs.get(png["_id"], kind="document") == (b"\x89PNG....", "image/png")
    assert not (store_db / "documents").exists(), "no files beside the database"
    row = next(x for x in d["documents"] if x["name"] == "shot.png")
    assert row["editable"] is False and row["is_image"] is True and row["size"] == 8


def test_html_upload_is_a_file_document(doc_client):
    d = _upload(doc_client, "inv1", ("page.html", b"<script>alert(1)</script>", "text/html"))
    row = d["documents"][0]
    assert row["kind"] == "file" and row["editable"] is False
    stored = store.get(row["id"])
    assert stored["body"] is None and stored["file_ext"] == "html"


def test_upload_reports_empty_and_missing_parent(doc_client):
    d = _upload(doc_client, "inv1", ("empty.md", b"", "text/markdown"),
                      ("ok.txt", b"fine", "text/plain"))
    assert d["ok"] is False and "empty" in d["errors"][0] and len(d["documents"]) == 1
    d2 = _upload(doc_client, "nope", ("a.md", b"x", "text/markdown"))
    assert d2["ok"] is False and "item not found" in d2["errors"][0] and d2["documents"] == []
    assert store.count({"parent_id": "nope"}) == 0


def test_text_cap(doc_client):
    with pytest.raises(DomainError):
        documents.add_upload("inventory", "inv1", "big.md", "text/markdown",
                                   b"x" * (documents.TEXT_CAP + 1))
    with pytest.raises(DomainError):
        documents.add_upload("inventory", "inv1", "bad.md", "text/markdown", b"\xff\xfe")


def test_new_note_is_blank_markdown(doc_client):
    r = doc_client.post("/api/inventory/inv1/notes", json={"name": "Meeting"})
    d = r.json()
    assert d["name"] == "Meeting.md" and d["kind"] == "md" and d["editable"] is True
    row = store.get(d["id"])
    assert row["body"] == "" and row["parent_id"] == "inv1" and row["parent_table"] == "inventory"
    r2 = doc_client.post("/api/inventory/nope/notes", json={"name": "x"})
    assert r2.status_code == 404 and r2.json()["ok"] is False


# --- edits --------------------------------------------------------------------------------

def test_edit_and_rename_dirty_diff(doc_client):
    r = doc_client.post("/api/documents/d1", json={"updates": {"body": "# New\n"}})
    assert r.json()["ok"] and r.json()["document"]["size"] == 6
    row = store.get("d1")
    assert row["body"] == "# New\n" and row["name"] == "repro.md" and row["size"] == 6
    r2 = doc_client.post("/api/documents/d1", json={"updates": {"name": "steps.txt"}})
    assert r2.json()["ok"] and r2.json()["document"]["kind"] == "txt"
    row = store.get("d1")
    assert row["body"] == "# New\n" and row["kind"] == "txt" and row["_edited_at"] is not None
    r3 = doc_client.post("/api/documents/d1", json={"updates": {"name": ""}})
    assert r3.status_code == 400
    assert (doc_client.post("/api/documents/nope", json={"updates": {"name": "x"}})).status_code == 404


def test_file_document_keeps_kind_on_rename_and_body_not_editable(doc_client):
    row = (_upload(doc_client, "inv1", ("a.png", b"\x89PNG", "image/png")))["documents"][0]
    r = doc_client.post(f"/api/documents/{row['id']}", json={"updates": {"body": "x"}})
    assert r.status_code == 400
    r2 = doc_client.post(f"/api/documents/{row['id']}", json={"updates": {"name": "a.md"}})
    assert r2.json()["ok"] and r2.json()["document"]["kind"] == "file"


def test_large_note_body_is_accepted_by_the_body_limit(doc_client):
    body = "x" * (100 * 1024)                     # over the 64 KB JSON cap, under TEXT_CAP
    r = doc_client.post("/api/documents/d1", json={"updates": {"body": body}})
    assert r.status_code == 200 and (store.get("d1"))["size"] == 100 * 1024


# --- raw bytes ------------------------------------------------------------------------------

def test_raw_text_is_a_download_and_images_may_inline(doc_client):
    r = doc_client.get("/api/documents/d1/raw")
    assert r.status_code == 200 and r.text.startswith("# Repro")
    assert r.headers["content-disposition"].startswith('attachment; filename="repro.md"')
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["cache-control"] == "no-store" and "sandbox" not in r.headers["content-security-policy"]
    png = (_upload(doc_client, "inv1", ("a.png", b"\x89PNG", "image/png")))["documents"][0]
    r2 = doc_client.get(f"/api/documents/{png['id']}/raw")
    assert r2.status_code == 200 and r2.content == b"\x89PNG"
    assert r2.headers["content-type"].startswith("image/png")
    assert r2.headers["content-disposition"].startswith("inline")
    r3 = doc_client.get(f"/api/documents/{png['id']}/raw?download=1")
    assert r3.headers["content-disposition"].startswith("attachment")
    assert (doc_client.get("/api/documents/nope/raw")).status_code == 404


def test_raw_frames_html_sandboxed_and_pdf_plain_never_svg(doc_client):
    d = _upload(doc_client, "inv1",
                      ("scan.pdf", b"%PDF-1.4", "application/pdf"),
                      ("logo.svg", b"<svg onload=alert(1)/>", "image/svg+xml"),
                      ("page.html", b"<script>alert(1)</script>", "text/html"))
    by_name = {x["name"]: x for x in d["documents"]}
    html = doc_client.get(f"/api/documents/{by_name['page.html']['id']}/raw")
    assert html.status_code == 200 and html.headers["content-disposition"].startswith("inline")
    assert html.headers["content-security-policy"] == "sandbox allow-scripts allow-forms allow-popups"
    assert html.headers["x-frame-options"] == "SAMEORIGIN"
    assert html.headers["x-content-type-options"] == "nosniff" and html.headers["cache-control"] == "no-store"
    assert html.headers.get_list("content-security-policy") == [html.headers["content-security-policy"]]
    pdf = doc_client.get(f"/api/documents/{by_name['scan.pdf']['id']}/raw")
    assert pdf.headers["content-disposition"].startswith("inline")
    assert pdf.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert pdf.headers["x-frame-options"] == "SAMEORIGIN"
    assert (doc_client.get(f"/api/documents/{by_name['scan.pdf']['id']}/raw?download=1")
            ).headers["content-disposition"].startswith("attachment")
    svg = doc_client.get(f"/api/documents/{by_name['logo.svg']['id']}/raw")
    assert svg.headers["content-disposition"].startswith("attachment")
    assert svg.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in svg.headers["content-security-policy"]
    # a .md keeps the app's own headers and is a download: the browser must not render it
    md = doc_client.get("/api/documents/d1/raw")
    assert md.headers["x-frame-options"] == "DENY"


def test_raw_missing_blob_is_404_not_500(doc_client):
    row = (_upload(doc_client, "inv1", ("a.png", b"\x89PNG", "image/png")))["documents"][0]
    blobs.delete(row["id"])
    r = doc_client.get(f"/api/documents/{row['id']}/raw")
    assert r.status_code == 404 and r.json()["ok"] is False


# --- delete ---------------------------------------------------------------------------------

def test_delete_audits_removes_blob_and_tolerates_missing(doc_client):
    row = (_upload(doc_client, "inv1", ("a.png", b"\x89PNG", "image/png")))["documents"][0]
    assert blobs.meta(row["id"]) is not None
    r = doc_client.post(f"/api/documents/{row['id']}/delete")
    assert r.json() == {"ok": True, "deleted": 1}
    assert store.get(row["id"]) is None and blobs.meta(row["id"]) is None
    logged = deletions.one({"collection": "documents"})
    assert logged is not None and logged["doc"]["_id"] == row["id"]
    row2 = (_upload(doc_client, "inv1", ("b.png", b"\x89PNG", "image/png")))["documents"][0]
    blobs.delete(row2["id"])
    assert (doc_client.post(f"/api/documents/{row2['id']}/delete")).json()["deleted"] == 1
    assert (doc_client.post("/api/documents/nope/delete")).status_code == 404


def test_item_delete_cascades_documents_with_audit_and_keeps_blobs(doc_client):
    png = (_upload(doc_client, "inv1", ("a.png", b"\x89PNG", "image/png")))["documents"][0]
    doc_client.post("/api/inventory/inv1/notes", json={"name": "Warranty"})
    r = doc_client.post("/api/inventory/delete", json={"ids": ["inv1"]})
    assert r.json() == {"ok": True, "deleted": 1}
    assert store.count({"parent_id": "inv1"}) == 0
    assert store.get("d1") is not None, "inv2's document is untouched"
    assert deletions.count({"collection": "documents"}) == 2
    assert deletions.count({"collection": "inventory"}) == 1
    assert blobs.get(png["id"]) == (b"\x89PNG", "image/png"), "Blobs stay (ADR-0005 addendum)"


# --- pages and wiring ------------------------------------------------------------------------

def test_inventory_page_carries_documents_without_bodies(doc_client):
    r = doc_client.get("/inventory")
    assert r.status_code == 200
    assert "repro.md" in r.text and '"_documents"' in r.text and "documentsEnabled: true" in r.text
    assert "# Repro" not in r.text
    assert 'id="card-docs"' in r.text
    r2 = doc_client.get("/accounts")
    assert 'id="card-docs"' not in r2.text and "documentsEnabled: false" in r2.text


def test_document_page_by_kind(doc_client):
    r = doc_client.get("/documents/d1")
    assert r.status_code == 200 and "<h1>Repro</h1>" in r.text and "markdown-body" in r.text
    assert "Pen" in r.text and 'href="/inventory"' in r.text     # back link to the parent page
    r_edit = doc_client.get("/documents/d1?edit=1")
    assert "<textarea" in r_edit.text and "doc-save" in r_edit.text
    d = _upload(doc_client, "inv1",
                      ("page.html", b"<h1>x</h1><script>alert(1)</script>", "text/html"),
                      ("a.png", b"\x89PNG", "image/png"),
                      ("scan.pdf", b"%PDF", "application/pdf"),
                      ("plain.txt", b"<b>not bold</b>", "text/plain"))
    by_name = {x["name"]: x for x in d["documents"]}
    html = doc_client.get(f"/documents/{by_name['page.html']['id']}")
    assert "alert(1)" not in html.text and "<iframe" in html.text
    assert 'sandbox="allow-scripts allow-forms allow-popups"' in html.text and "No preview" not in html.text
    assert (doc_client.get(f"/documents/{by_name['page.html']['id']}?edit=1")).text.count("<textarea") == 0
    png = doc_client.get(f"/documents/{by_name['a.png']['id']}")
    assert "<img" in png.text and "raw" in png.text
    pdf = doc_client.get(f"/documents/{by_name['scan.pdf']['id']}")
    assert "<iframe" in pdf.text and "sandbox=" not in pdf.text and "No preview" not in pdf.text
    other = (_upload(doc_client, "inv1", ("data.bin", b"\x00\x01", "application/octet-stream")))["documents"][0]
    r_other = doc_client.get(f"/documents/{other['id']}")
    assert "No preview" in r_other.text and "<iframe" not in r_other.text and "download=" in r_other.text
    txt = doc_client.get(f"/documents/{by_name['plain.txt']['id']}")
    assert "doc-plain" in txt.text and "<b>not bold</b>" not in txt.text and "&lt;b&gt;" in txt.text
    assert (doc_client.get("/documents/nope")).status_code == 404


def test_render_preview_endpoint(doc_client):
    r = doc_client.post("/api/documents/render", json={"body": "*hi*"})
    assert r.json()["html"].strip() == "<p><em>hi</em></p>"


def test_document_routes_registered():
    inv = set(dbhelper.routes(_inventory.urlpatterns()))
    assert "/api/inventory/<str:doc_id>/documents" in inv
    assert "/api/inventory/<str:doc_id>/notes" in inv
    acc = dbhelper.routes(_accounts.urlpatterns())
    assert not any(p.endswith(("/documents", "/notes")) for p in acc)
    paths = dbhelper.routes(documents_views)
    assert paths.index("/api/documents/render") < paths.index("/api/documents/<str:doc_id>")
    assert documents.PARENTS["inventory"].back_url == "/inventory"
