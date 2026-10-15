// Category-mapping editor island — shared by Tax and Savings (CONTEXT.md: Category mapping).
// Wires the "Sync new categories" button and per-row role/field edits to the endpoints in
//   window.MAPPING_EDITOR = { endpoint, syncEndpoint, reloadOnChange }
// Markup convention: each row is [data-cat="<category>"]; each editable control inside carries
// [data-map="<field>"] (e.g. role, deduction_type, schedule). Self-contained — pages keep their
// own JS for charts / goals / config. This is the frontend twin of app/category_mapping.py.
(function () {
  const cfg = window.MAPPING_EDITOR;
  if (!cfg) return;

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || "request failed");
    return data;
  }

  // Per-row edits: each [data-map="field"] control POSTs {category, field: value}.
  document.querySelectorAll("[data-cat]").forEach((row) => {
    const cat = row.getAttribute("data-cat");
    if (!cat) return;
    row.querySelectorAll("[data-map]").forEach((el) => {
      el.addEventListener("change", async () => {
        const body = { category: cat };
        body[el.getAttribute("data-map")] = el.value;
        try {
          await postJSON(cfg.endpoint, body);
          if (cfg.reloadOnChange) location.reload();
        } catch (err) {
          alert("Could not update mapping: " + err.message);
        }
      });
    });
  });

  // Sync: append newly-seen ledger categories, then repaint.
  const syncBtn = document.getElementById("sync-mapping");
  if (syncBtn && cfg.syncEndpoint) {
    syncBtn.addEventListener("click", async () => {
      try {
        const d = await postJSON(cfg.syncEndpoint, {});
        alert("Added " + d.added + " new categories.");
        location.reload();
      } catch (err) {
        alert("Sync failed: " + err.message);
      }
    });
  }
})();
