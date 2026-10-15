// Tax — config / history / category-mapping CRUD. Mutations POST JSON to /api/tax/* then
// reload to repaint the server-rendered tables.
(function () {
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

  function formToObj(form) {
    const o = {};
    new FormData(form).forEach((v, k) => { o[k] = v; });
    return o;
  }

  function wireForm(id, url) {
    const form = document.getElementById(id);
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await postJSON(url, formToObj(form)); location.reload(); }
      catch (err) { alert("Could not save: " + err.message); }
    });
  }

  wireForm("tax-config", "/api/tax/config");
  wireForm("history-form", "/api/tax/history");

  document.querySelectorAll("[data-del-history]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this history row?")) return;
      try { await postJSON("/api/tax/history/delete", { id: btn.getAttribute("data-del-history") }); location.reload(); }
      catch (err) { alert("Could not delete: " + err.message); }
    });
  });

  // Category-mapping editor (sync button + per-row role/deduction edits) is the shared
  // mapping-editor.js island, wired by window.MAPPING_EDITOR in tax.html.
})();
