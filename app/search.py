"""Search — the one matching rule every search in the app shares: the Inventory card board
(client-side, mirrored in app/static/js/card-editor.js), the Column view's tree query, and the
clipper's item picker. Up to MAX_TOKENS whitespace-separated words; every word must be a
case-insensitive substring of at least one of the given fields (AND across words, OR across
fields). No words → everything matches. Keep the JS mirror in lockstep."""

MAX_TOKENS = 6


def tokens(q) -> list[str]:
    """Up to MAX_TOKENS lower-cased words; '' / None → []."""
    return [t.lower() for t in str(q or "").split()][:MAX_TOKENS]


def matches(doc: dict, q, fields) -> bool:
    toks = tokens(q)
    if not toks:
        return True
    hay = [str(doc.get(f) or "").lower() for f in fields]
    return all(any(t in h for h in hay) for t in toks)
