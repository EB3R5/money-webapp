"""Software import — one host's "what is installed" run, upserted on `source_key`
(ADR-0017; the contract scripts/export_installed.py in future-purchases produces).

Idempotent: a known key updates in place, an unknown one mints SW-###. Ownership per
field is software_item's OVERWRITE_FIELDS / FILL_FIELDS — user-curated fields (Status,
Cost, Notes, …) are set on insert only. Install_Locations merge per host: this host's
entries are replaced, other hosts' are kept. A key this host reported before but not now
loses that host (and flips to `uninstalled` while its Status is still automatic — see
status_for_import). The sweep is scoped to the managers this run actually collected, so
a partial run never uninstalls what it didn't look at. Re-posting the same export is a
no-op (updated: 0).

Pure orchestration over the software store; the route (app/views/software_sync.py) only
parses the body. A later script can call apply_run in-process on a run file."""

import secrets
from datetime import UTC, datetime

from .views.software import _on_create
from .software_item import FILL_FIELDS, OVERWRITE_FIELDS, from_wire, status_for_import
from .store.software import software


def _locations(entry: dict, host: str, seen_at):
    """This host's install locations from the entry, host-stamped. Entries for other
    hosts inside one host's export are ignored — a run speaks for one machine."""
    out = []
    for loc in entry.get("install_locations") or []:
        if not isinstance(loc, dict) or not loc.get("manager") or not loc.get("id"):
            continue
        if loc.get("host") and loc["host"] != host:
            continue
        out.append({"host": host, "manager": str(loc["manager"]), "id": str(loc["id"]),
                    "version": loc.get("version"), "seen_at": loc.get("seen_at") or seen_at})
    return out


def _sig(locs):
    return sorted((l.get("host"), l.get("manager"), l.get("id"), l.get("version")) for l in locs or [])


def validate(body) -> str | None:
    """The request contract: {host, collected_at?, managers: [...], entries: [...]}."""
    if not isinstance(body, dict) or not isinstance(body.get("host"), str) or not body["host"].strip():
        return "expected {host, collected_at, managers, entries}"
    if not isinstance(body.get("entries"), list) or not isinstance(body.get("managers"), list):
        return "entries and managers must be lists"
    return None


def apply_run(body: dict) -> dict:
    """Upsert one host's run. Returns the summary the endpoint answers with:
    {status, host, added, updated, unchanged, removed, skipped, items}."""
    err = validate(body)
    if err:
        return {"status": "error", "error": err}
    host = body["host"].strip()
    seen_at = body.get("collected_at") or datetime.now(UTC).replace(microsecond=0).isoformat()
    managers = [str(m) for m in body["managers"]]

    added = updated = unchanged = removed = skipped = 0
    items, seen = [], set()
    mint_n = software.max_sw_num()

    for entry in body["entries"]:
        sk = entry.get("source_key") if isinstance(entry, dict) else None
        if not isinstance(sk, str) or ":" not in sk:
            skipped += 1
            continue
        sk = sk.strip()
        seen.add(sk)
        fields = from_wire(entry)
        fields.pop("Source_Key", None)
        locs_in = _locations(entry, host, seen_at)
        if locs_in and locs_in[0].get("version") and "Version_Installed" not in fields:
            fields["Version_Installed"] = locs_in[0]["version"]

        existing = software.one({"Source_Key": sk})
        if existing is None:
            mint_n += 1
            st = status_for_import(None, bool(locs_in), entry.get("status"))
            doc = {"_id": "man_" + secrets.token_hex(10), "_src": "import",
                   "SW_ID": f"SW-{mint_n:03d}", "Source_Key": sk, **fields,
                   "Install_Locations": locs_in, "Status": st, "_import_status": st}
            _on_create(doc)
            software.insert(doc)
            added += 1
            items.append({"source_key": sk, "id": doc["SW_ID"], "_id": doc["_id"], "action": "added"})
            continue

        merged = [l for l in existing.get("Install_Locations") or [] if l.get("host") != host] + locs_in
        changes = {}
        for k in OVERWRITE_FIELDS:
            if k == "Install_Locations":
                if _sig(merged) != _sig(existing.get("Install_Locations")):
                    changes[k] = merged
            elif k in fields and existing.get(k) != fields[k]:
                changes[k] = fields[k]
        for k in FILL_FIELDS:
            if k in fields and not existing.get(k):
                changes[k] = fields[k]
        st = status_for_import(existing, bool(merged))
        if st:
            changes["Status"] = st
            changes["_import_status"] = st
        if not changes:
            unchanged += 1
            items.append({"source_key": sk, "id": existing.get("SW_ID"), "_id": existing["_id"], "action": "unchanged"})
            continue
        software.update(existing["_id"], changes)
        updated += 1
        items.append({"source_key": sk, "id": existing.get("SW_ID"), "_id": existing["_id"], "action": "updated"})

    # Removal sweep: keys this host+managers reported before but not in this run. No JSON
    # predicate in the store, so the (small, personal) table is read and filtered here.
    if managers:
        mset = set(managers)

        def here(l):
            return l.get("host") == host and l.get("manager") in mset

        for d in software.list():
            if d.get("Source_Key") in seen:
                continue
            locs = d.get("Install_Locations") or []
            if not any(here(l) for l in locs):
                continue
            remaining = [l for l in locs if not here(l)]
            changes = {"Install_Locations": remaining}
            st = status_for_import(d, bool(remaining))
            if st:
                changes["Status"] = st
                changes["_import_status"] = st
            software.update(d["_id"], changes)
            removed += 1
            items.append({"source_key": d.get("Source_Key"), "id": d.get("SW_ID"), "_id": d["_id"],
                          "action": "removed"})

    return {"status": "ok", "host": host, "added": added, "updated": updated,
            "unchanged": unchanged, "removed": removed, "skipped": skipped, "items": items}
