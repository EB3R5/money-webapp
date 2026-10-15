// Income page — the sources form (add, or edit when prefilled from a row), activate /
// deactivate, delete with confirmation, and "Use this" from a detected series. csrf.js
// stamps the token on every fetch; the page reloads after each write so the server renders.
(function () {
  const $ = (s) => document.querySelector(s);
  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || "request failed");
    return data;
  }
  const form = $("#source-form"), title = $("#form-title"), submit = $("#src-submit"), cancel = $("#src-cancel"), status = $("#src-status");
  const fields = { id: $("#src-id"), name: $("#src-name"), category: $("#src-category"), cadence: $("#src-cadence"),
                   amount: $("#src-amount"), anchor_date: $("#src-anchor"), notes: $("#src-notes") };

  function fill(d, editing) {
    fields.id.value = editing ? d.edit : "";
    fields.name.value = d.name || ""; fields.category.value = d.category || "";
    fields.cadence.value = d.cadence || "monthly"; fields.amount.value = d.amount || "";
    fields.anchor_date.value = d.anchor || ""; fields.notes.value = d.notes || "";
    title.textContent = editing ? "Edit source" : "Add a source";
    submit.textContent = editing ? "Save changes" : "Add source";
    cancel.hidden = !editing; status.textContent = "";
    fields.name.focus();
    form.scrollIntoView({ block: "nearest" });
  }
  function reset() { fill({}, false); fields.cadence.value = "monthly"; }

  document.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => fill(b.dataset, true)));
  document.querySelectorAll("[data-use]").forEach((b) => b.addEventListener("click", () => fill(b.dataset, false)));
  cancel.addEventListener("click", reset);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { name: fields.name.value, category: fields.category.value, cadence: fields.cadence.value,
                   amount: fields.amount.value, anchor_date: fields.anchor_date.value, notes: fields.notes.value };
    status.textContent = "Saving…";
    try {
      if (fields.id.value) await postJSON("/api/planning/income/update", { id: fields.id.value, ...body });
      else await postJSON("/api/planning/income", body);
      location.reload();
    } catch (err) { status.textContent = "Error: " + err.message; }
  });

  document.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", async () => {
    try { await postJSON("/api/planning/income/update", { id: b.dataset.toggle, active: b.dataset.active !== "1" }); location.reload(); }
    catch (err) { alert("Could not update: " + err.message); }
  }));
  document.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Delete this income source? Recovery is manual (deletions log).")) return;
    try { await postJSON("/api/planning/income/delete", { id: b.dataset.del }); location.reload(); }
    catch (err) { alert("Could not delete: " + err.message); }
  }));
})();
