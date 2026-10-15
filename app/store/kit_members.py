"""Kit members — one row per (Kit, member), the member named as (member_table, member_id)
(ADR-0018). On the wire a member is a **member key**, `inventory:<row id>` or
`software:<row id>`; this module is the one place the key meets the two columns.

The store knows nothing of the member tables themselves: it accepts any well-formed key
whose table is one of MEMBER_TABLES. Whether the row exists is the domain layer's check
(app/kits.py resolves members and skips the dangling)."""

from .base import Field, Store, q

TABLE = "kit_members"
MEMBER_TABLES = ("inventory", "software")

FIELDS = (
    Field("kit_id", "kit_id", "text"),
    Field("member_table", "member_table", "text"),
    Field("member_id", "member_id", "text"),
    Field("position", "position", "int"),
)


def member_key(table: str, row_id: str) -> str:
    return f"{table}:{row_id}"


def split_key(key) -> tuple[str, str] | None:
    """'inventory:abc' → ('inventory', 'abc'); None for anything malformed or an unknown table."""
    if not isinstance(key, str) or ":" not in key:
        return None
    table, _, row_id = key.partition(":")
    if table not in MEMBER_TABLES or not row_id:
        return None
    return table, row_id


class KitMembersStore(Store):
    def list_for_kit(self, kit_id: str) -> list[dict]:
        """The Kit's memberships in position order, each with `key`."""
        rows = self.list({"kit_id": kit_id}, order=[("position", "asc")])
        for r in rows:
            r["key"] = member_key(r["member_table"], r["member_id"])
        return rows

    def list_for_members(self, table: str, ids) -> dict[str, list[dict]]:
        """{member key: [{"id", "name"} of each Kit, by name]} for many rows of one table in
        one query — what a card page attaches to its rows as `_kits`."""
        ids = [str(i) for i in ids]
        if not ids or table not in MEMBER_TABLES:
            return {}
        marks = ", ".join("?" for _ in ids)
        rows = self.rows(
            f"SELECT m.member_id, k.id, k.name FROM {q(self.table)} m "
            f"JOIN kits k ON k.id = m.kit_id "
            f"WHERE m.member_table = ? AND m.member_id IN ({marks}) "
            f"ORDER BY k.name COLLATE NOCASE, k.id", [table, *ids])
        out: dict[str, list[dict]] = {}
        for member_id, kit_id, name in rows:
            out.setdefault(member_key(table, member_id), []).append({"id": kit_id, "name": name})
        return out

    def add(self, kit_id: str, keys) -> list[str]:
        """Append the members in the order given at max(position)+1. A malformed key, an
        unknown table, a repeat within the call or a member already in the Kit is skipped.
        Returns the keys actually added."""
        wanted = []
        seen = set()
        for k in keys or []:
            parts = split_key(k)
            if parts and k not in seen:
                seen.add(k)
                wanted.append((k, *parts))
        if not wanted:
            return []
        with self.db.scope():
            have = {r["key"] for r in self.list_for_kit(kit_id)}
            top = self.rows(f"SELECT COALESCE(MAX(position), 0) FROM {q(self.table)} WHERE kit_id = ?", [kit_id])
            position = int(top[0][0]) if top else 0
            added = []
            for key, table, row_id in wanted:
                if key in have:
                    continue
                position += 1
                self.insert({"kit_id": kit_id, "member_table": table, "member_id": row_id,
                                   "position": position})
                added.append(key)
        return added

    def remove(self, kit_id: str, keys) -> int:
        """Drop the given members from the Kit; unknown keys are ignored. Returns the count."""
        n = 0
        for k in keys or []:
            parts = split_key(k)
            if parts:
                n += self.delete_where(kit_id=kit_id, member_table=parts[0], member_id=parts[1])
        return n

    def delete_for_members(self, table: str, ids) -> int:
        """The cascade an Item's or Software's deletion runs: every membership of those rows,
        in every Kit."""
        ids = [str(i) for i in ids]
        if not ids or table not in MEMBER_TABLES:
            return 0
        return self.delete_where(member_table=table, member_id=ids)


kit_members = KitMembersStore(TABLE, FIELDS)
