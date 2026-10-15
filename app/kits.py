"""Kits — the domain rules behind the Kit page (CONTEXT.md, ADR-0018, plan D2/D6–D8).

A Kit is a view over owned things: its members are rows of `inventory` and `software`,
named by member key (`inventory:<row id>` / `software:<row id>`, store/kit_members.py). This
module resolves those keys to what the page shows — each member exactly as its own board
serializes it (title, subtitle, amount, photos), plus where a tile goes — and derives what a
Kit has no column for: its cover, its stats, its rendered how-to. A membership whose member
row is gone is skipped, never shown as a hole. Routes live in app/views/kits.py."""

from . import documents
from .views.inventory import _inventory
from .views.software import _software
from .software_item import ACTIVE_STATUSES
from .store.inventory import inventory
from .store.kit_members import kit_members, member_key, split_key
from .store.software import software

# The fields the transfer list's filter searches (app/search.py rule, per member table).
SEARCH_FIELDS = {"inventory": ["Item_Name", "Brand", "Model", "Category"],
                 "software": ["Item_Name", "Vendor", "Kind", "Category"]}


def kit_image_url(entry: dict) -> str:
    return "/api/kits/image/" + entry["id"]


def _item(table: str, s: dict, image_base: str) -> dict:
    """One member as the page and the transfer list see it."""
    imgs = [image_base + im["id"] for im in (s.get("_images") or []) if im.get("id")]
    link = s.get("Link") or ""
    status = s.get("Status") if table == "software" else None
    active = status in ACTIVE_STATUSES if table == "software" else True
    if table == "inventory":
        href = f"/inventory/{s['_id']}/sheet"
    else:
        from urllib.parse import quote
        href = "/software?q=" + quote(s.get("_title") or "")
    return {
        "key": member_key(table, s["_id"]), "table": table, "id": s["_id"],
        "title": s.get("_title") or "(untitled)", "subtitle": s.get("_subtitle") or "",
        "amount": s.get("_amount"), "image": imgs[0] if imgs else None, "images": imgs,
        "link": link if link.startswith("http") else None, "href": href,
        "status": status, "active": active,
        "search": [str(s.get(f) or "") for f in SEARCH_FIELDS[table]],
    }


def catalog() -> dict[str, dict]:
    """Every Item and every Software (any Status), keyed by member key, each serialized by
    its own CardCollection so title, subtitle, amount and photos match the boards."""
    out: dict[str, dict] = {}
    for d in inventory.list():
        s = _inventory.serialize(d)
        out[member_key("inventory", s["_id"])] = _item("inventory", s, "/api/inventory/image/")
    for d in software.list():
        s = _software.serialize(d)
        out[member_key("software", s["_id"])] = _item("software", s, "/api/software/image/")
    return out


def resolve(membership_rows: list[dict], cat: dict) -> list[dict]:
    """Members in position order; a key with no catalog row (dangling) is skipped."""
    return [cat[r["key"]] for r in membership_rows if r["key"] in cat]


def stats(members: list[dict]) -> dict:
    inv = [m for m in members if m["table"] == "inventory"]
    sw = [m for m in members if m["table"] == "software"]
    return {
        "count": len(members), "n_inv": len(inv), "n_sw": len(sw),
        "value": round(sum(m["amount"] or 0 for m in inv), 2),
        # only active software is a running cost (plan D2): cancelled / uninstalled add nothing
        "monthly": round(sum(m["amount"] or 0 for m in sw if m["active"]), 2),
        "with_photo": sum(1 for m in members if m["image"]),
    }


def cover(kit: dict, members: list[dict]) -> str | None:
    """The hero: the Kit's first own photo, else the first member photo, else None."""
    own = [kit_image_url(im) for im in (kit.get("_images") or []) if im.get("id")]
    if own:
        return own[0]
    for m in members:
        if m["image"]:
            return m["image"]
    return None


def view(kit: dict, membership_rows: list[dict], cat: dict) -> dict:
    """One Kit as the page renders it: the serialized row plus everything derived."""
    members = resolve(membership_rows, cat)
    st = stats(members)
    return {
        **kit, "members": members, "member_keys": [m["key"] for m in members],
        "cover": cover(kit, members), "stats": st,
        "how_to_html": documents.render_markdown(kit.get("How_To") or ""),
        "photos": [kit_image_url(im) for im in (kit.get("_images") or []) if im.get("id")],
    }


def available(cat: dict, member_keys: list[str], in_kits: dict[str, int]) -> list[dict]:
    """The transfer list's left side: every catalogued member not in this Kit, by title,
    each with the number of Kits it is already in. The page filters it client-side with the
    Search rule's JS mirror (window.searchHit) over each row's `search` fields."""
    have = set(member_keys)
    rows = [{**m, "in_kits": in_kits.get(m["key"], 0)} for k, m in cat.items() if k not in have]
    return sorted(rows, key=lambda m: (m["title"].lower(), m["key"]))


def valid_keys(keys, cat: dict) -> list[str]:
    """The well-formed keys that name a catalogued row, in the order given, deduplicated."""
    out, seen = [], set()
    for k in keys or []:
        if split_key(k) and k in cat and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def memberships_by_kit() -> dict[str, list[dict]]:
    """{kit id: membership rows in position order}, one query for the whole page."""
    rows = kit_members.list(order=[("kit_id", "asc"), ("position", "asc")])
    out: dict[str, list[dict]] = {}
    for r in rows:
        r["key"] = member_key(r["member_table"], r["member_id"])
        out.setdefault(r["kit_id"], []).append(r)
    return out


def kit_counts(by_kit: dict[str, list[dict]]) -> dict[str, int]:
    """{member key: number of Kits it belongs to} for the "in N kits" hint."""
    counts: dict[str, int] = {}
    for rows in by_kit.values():
        for r in rows:
            counts[r["key"]] = counts.get(r["key"], 0) + 1
    return counts
