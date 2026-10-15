// Notebook page island. View mode: a prompt chip appends its sentence to the saved body
// through the entry API and reopens the page in Write mode, so the sentence is never lost
// in a page hop. Write mode: textarea + live preview (the server renders the Markdown, so
// view and preview never differ), dirty-aware Save, Ctrl-S, leave guard, chips append
// into the textarea. csrf.js stamps the token on every fetch.
(function () {
  const N = window.NOTEBOOK;
  const $ = (s) => document.querySelector(s);
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) }).then((r) => r.json());
  const entryUrl = "/api/planning/entry/" + N.period;
  const append = (text, sentence) => text.replace(/\s*$/, "") + (text.trim() ? "\n\n" : "") + sentence.trim() + " ";
  const chips = $("#nb-chips");

  if (!N.edit) {
    if (chips) chips.addEventListener("click", (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      b.disabled = true;
      post(entryUrl, { body: append(N.body, b.textContent) })
        .then((d) => { if (d.ok) location.href = "/planning/notebook/" + N.period + "?edit=1"; else b.disabled = false; })
        .catch(() => { b.disabled = false; });
    });
    return;
  }

  const ta = $("#nb-body"), save = $("#nb-save"), status = $("#nb-status"), preview = $("#nb-preview");
  let original = ta.value, t;

  function render() {
    post("/api/documents/render", { body: ta.value }).then((d) => { preview.innerHTML = d.html || ""; }).catch(() => {});
  }
  ta.addEventListener("input", () => {
    save.disabled = ta.value === original;
    clearTimeout(t); t = setTimeout(render, 300);
  });
  ta.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const s = ta.selectionStart, end = ta.selectionEnd;
    ta.value = ta.value.slice(0, s) + "  " + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = s + 2;
    ta.dispatchEvent(new Event("input"));
  });
  if (chips) chips.addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    ta.value = append(ta.value, b.textContent);
    b.remove();
    ta.dispatchEvent(new Event("input")); ta.focus();
    ta.selectionStart = ta.selectionEnd = ta.value.length;
  });

  function doSave() {
    if (ta.value === original) return;
    status.textContent = "Saving…"; save.disabled = true;
    post(entryUrl, { body: ta.value })
      .then((d) => {
        if (!d.ok) { status.textContent = "Error: " + (d.error || "failed"); save.disabled = false; return; }
        original = ta.value; N.body = ta.value; status.textContent = "✓ Saved";
      })
      .catch(() => { status.textContent = "Network error"; save.disabled = false; });
  }
  save.addEventListener("click", doSave);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); doSave(); }
  });
  window.addEventListener("beforeunload", (e) => { if (ta.value !== original) { e.preventDefault(); e.returnValue = ""; } });
})();
