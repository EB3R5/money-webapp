"""Inventory Item export — the pure half of "export one Item as a bundle".

An Item bundle is a zip that unpacks to one self-contained folder:

    Dyson V11 (a3f9)/
      item.md          front matter (every declared field + Value + exported_at) and a body
      card.png         the Item sheet as the browser captured it (absent if not supplied)
      photos/01.jpg    the stored photos, originals, numbered in stored order

The folder is named from the Item's name plus a short id suffix so two Items with the
same name never collide and a folder can always be traced back to its record. Photos
link from the Markdown by relative path, so the folder works as-is in a file browser
and drops into an Obsidian vault as one note with its attachments.

No web or database code lives here: the router (views/inventory_export.py) fetches
the doc, the photo bytes, and the posted PNG, and this module turns them into bytes.
`sheet_context` is the sheet template's view-model, kept here so the sheet and the
Markdown agree on which photo is the hero and which fields are shown.
"""

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Iterable, Optional

from .inventory_item import SHEET_HIDDEN, export_fields, value

MD_NAME = "item.md"
PNG_NAME = "card.png"
PHOTOS_DIR = "photos"

# Fields the sheet shows prominently (in the header) rather than in the spec table.
HEADLINE = ("Item_Name", "Brand", "Model")

_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp",
        "image/gif": "gif", "image/heic": "heic", "image/avif": "avif", "image/bmp": "bmp",
        "image/tiff": "tiff", "image/svg+xml": "svg"}


def short_id(doc_id) -> str:
    """Last four alphanumerics of the stored id's final segment — "man_…cc68" → "cc68",
    "raw__…__r35" → "r35". Enough to disambiguate, short enough to read."""
    seg = str(doc_id or "").split("__")[-1]
    return re.sub(r"[^A-Za-z0-9]", "", seg)[-4:]


def folder_name(doc: dict) -> str:
    """"<cleaned Item_Name> (<short id>)" — safe on every file system, never empty."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(doc.get("Item_Name") or "")).strip()
    name = re.sub(r"\s+", " ", name).strip(" .") or "item"
    return f"{name[:80].rstrip()} ({short_id(doc.get('_id')) or 'item'})"


def photo_ext(content_type: Optional[str], filename: Optional[str] = None) -> str:
    """File extension for a stored photo: from its content type, else its original name."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT:
        return _EXT[ct]
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", filename or "")
    return m.group(1).lower() if m else "bin"


def photo_paths(photos: Iterable[tuple]) -> list:
    """Relative in-bundle paths ("photos/01.jpg", …) for (bytes, content_type, filename)
    photo tuples, numbered in the order given."""
    return [f"{PHOTOS_DIR}/{i:02d}.{photo_ext(ct, fn)}"
            for i, (_data, ct, fn) in enumerate(photos, start=1)]


def _yaml_scalar(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(v)
    return json.dumps(str(v), ensure_ascii=False)   # a JSON string is a valid YAML string


def _label(field: str) -> str:
    return field.replace("_", " ")


def _spec_rows(doc: dict) -> list:
    """(label, value) for the descriptive fields that are filled — blanks hidden, headline
    and accounting-only fields left out, Notes handled as prose."""
    fields = export_fields(doc)
    rows = []
    for name, v in fields.items():
        if name in HEADLINE or name in SHEET_HIDDEN or name in ("Notes", "Value"):
            continue
        if str(v).strip():
            rows.append((_label(name), str(v).strip()))
    return rows


def sheet_context(doc: dict, photo_urls: list, kits: Iterable[dict] = ()) -> dict:
    """View-model for the Item sheet: hero + thumbnails, headline, spec rows, the Kits the
    Item belongs to ([{id, name}], a row only when there are any), notes."""
    fields = export_fields(doc)
    return {
        "kits": [{"id": k["id"], "name": k["name"]} for k in kits],
        "title": fields["Item_Name"] or "(unnamed item)",
        "brand": fields["Brand"], "model": fields["Model"],
        "value": fields["Value"],
        "hero": photo_urls[0] if photo_urls else None,
        "thumbs": photo_urls[1:],
        "rows": _spec_rows(doc),
        "notes": fields["Notes"].strip(),
        "link": fields["Link"].strip(),
    }


def markdown(doc: dict, photo_rel_paths: list, exported_at: Optional[datetime] = None,
             png_name: Optional[str] = PNG_NAME, kits: Iterable[dict] = ()) -> str:
    """`item.md`: YAML front matter (raw field names, every declared field, Value, the Kits
    the Item belongs to as `kits:` — a list of names, omitted when it is in none —
    exported_at) then hero image, spec table, remaining photos, notes."""
    exported_at = exported_at or datetime.now(UTC)
    fields = export_fields(doc)
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {_yaml_scalar(v)}")
    kit_names = [k["name"] for k in kits]
    if kit_names:
        lines.append("kits:")
        lines += [f"  - {_yaml_scalar(n)}" for n in kit_names]
    lines.append(f"exported_at: {_yaml_scalar(exported_at.isoformat(timespec='seconds'))}")
    lines += ["---", "", f"# {fields['Item_Name'] or '(unnamed item)'}", ""]

    sub = " · ".join(x for x in (fields["Brand"], fields["Model"]) if x.strip())
    if sub:
        lines += [f"*{sub}*", ""]
    if photo_rel_paths:
        lines += [f"![{fields['Item_Name']}]({photo_rel_paths[0]})", ""]

    lines += ["| Field | Value |", "|---|---|"]
    lines.append(f"| Value | ${fields['Value']:,.2f} |")
    for label, v in _spec_rows(doc):
        cell = v.replace("|", "\\|").replace("\n", " ")
        if label == "Link" and re.match(r"^https?://", v):
            cell = f"[{cell}]({v})"
        lines.append(f"| {label} | {cell} |")
    lines.append("")

    if len(photo_rel_paths) > 1:
        lines += ["## Photos", ""]
        lines += [f"![photo {i}]({p})" for i, p in enumerate(photo_rel_paths[1:], start=2)]
        lines.append("")
    if fields["Notes"].strip():
        lines += ["## Notes", "", fields["Notes"].strip(), ""]
    if png_name:
        lines += ["## Sheet", "", f"![sheet]({png_name})", ""]
    return "\n".join(lines)


def bundle(doc: dict, photos: list, png: Optional[bytes] = None,
           exported_at: Optional[datetime] = None, kits: Iterable[dict] = ()) -> tuple:
    """Build the zip. `photos` is [(bytes, content_type, filename)] in stored order (the
    router has already dropped any whose file is gone); `kits` is the Item's Kit list for
    the front matter. Returns (zip filename, bytes)."""
    folder = folder_name(doc)
    rel = photo_paths(photos)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/{MD_NAME}",
                   markdown(doc, rel, exported_at, PNG_NAME if png else None, kits))
        if png:
            z.writestr(f"{folder}/{PNG_NAME}", png)
        z.writestr(zipfile.ZipInfo(f"{folder}/{PHOTOS_DIR}/"), b"")   # keep the folder even if empty
        for path, (data, _ct, _fn) in zip(rel, photos):
            z.writestr(f"{folder}/{path}", data)
    return f"{folder}.zip", buf.getvalue()


__all__ = ["bundle", "markdown", "sheet_context", "folder_name", "photo_ext", "photo_paths",
           "short_id", "value"]
