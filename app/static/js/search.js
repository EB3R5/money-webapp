// The one JS mirror of app/search.py (up to 6 words, every word a case-insensitive substring
// of some field, AND across words): the card boards (card-editor.js) and the planning pages
// (planning-search.js) both read these. Keep in lockstep with the Python.
window.searchTokens = (q) => String(q || "").toLowerCase().split(/\s+/).filter(Boolean).slice(0, 6);
window.searchHit = (fields, item, toks) => {
  const hay = fields.map((f) => String(item[f] == null ? "" : item[f]).toLowerCase());
  return toks.every((t) => hay.some((h) => h.includes(t)));
};
