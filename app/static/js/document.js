// Document page island — in edit mode, a textarea with a live preview (Markdown is rendered
// by the server so view and preview never differ) and a dirty-aware Save. View mode only
// wires Print. csrf.js already stamps the token on every fetch.
(function () {
  const D = window.DOC;
  const $ = (s) => document.querySelector(s);
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) }).then((r) => r.json());
  $("#doc-print").addEventListener("click", () => window.print());
  if (!D.edit) return;

  const ta = $("#doc-body"), save = $("#doc-save"), status = $("#doc-status"), preview = $("#doc-preview");
  let original = ta.value, t;

  function render() {
    if (D.kind !== "md") { preview.textContent = ta.value; return; }
    post("/api/documents/render", { body: ta.value }).then((d) => { preview.innerHTML = d.html || ""; }).catch(() => {});
  }
  render();
  ta.addEventListener("input", () => {
    save.disabled = ta.value === original;
    clearTimeout(t); t = setTimeout(render, 300);
  });
  // Tab inserts two spaces instead of leaving the editor.
  ta.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const s = ta.selectionStart, end = ta.selectionEnd;
    ta.value = ta.value.slice(0, s) + "  " + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = s + 2;
    ta.dispatchEvent(new Event("input"));
  });

  function doSave() {
    if (ta.value === original) return;
    status.textContent = "Saving…"; save.disabled = true;
    post("/api/documents/" + encodeURIComponent(D.id), { updates: { body: ta.value } })
      .then((d) => {
        if (!d.ok) { status.textContent = "Error: " + (d.error || "failed"); save.disabled = false; return; }
        original = ta.value; status.textContent = "✓ Saved";
      })
      .catch(() => { status.textContent = "Network error"; save.disabled = false; });
  }
  save.addEventListener("click", doSave);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); doSave(); }
  });
  window.addEventListener("beforeunload", (e) => { if (ta.value !== original) { e.preventDefault(); e.returnValue = ""; } });
})();
