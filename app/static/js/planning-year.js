// Year plan — the detail card for a selected planned spend (with "Move to" buttons that warn
// when the target month would go negative), the add / edit form, mark done and delete.
// The server renders the page from year_plan(); the same facts sit in #plan-data for the
// card. Every write posts JSON then reloads. Widths come from data-w (CSP: no style attrs).
(function () {
  const $ = (s) => document.querySelector(s);
  const P = JSON.parse($("#plan-data").textContent);
  document.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w + "%"; });
  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || "request failed");
    return data;
  }
  const money = (v, s) => (s && v > 0 ? "+" : v < 0 ? "−" : "") + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const lab = (ym) => MON[+ym.slice(5, 7) - 1] + " " + ym.slice(2, 4);

  // every item by id: placed ones from the months, plus the shelf and the earlier strip
  const items = {};
  P.months.forEach((m) => m.items.forEach((it) => { items[it.id] = { ...it, month: m.month, net: m.net }; }));
  P.shelf.forEach((it) => { items[it.id] = { ...it, month: null, net: null }; });
  P.past.forEach((it) => { items[it.id] = { ...it, net: null, past: true }; });
  const netOf = Object.fromEntries(P.months.map((m) => [m.month, m.net]));

  function showDetail(id) {
    const it = items[id]; if (!it) return;
    document.querySelectorAll(".pin.sel, .chip.sel").forEach((e) => e.classList.remove("sel"));
    document.querySelectorAll(`[data-id="${id}"]`).forEach((e) => e.classList.add("sel"));
    const f = it.funding;
    const rows = [
      ["Group", it.group || "—"], ["Cadence", it.cadence],
      ["Source", it.origin === "future-purchases" ? `<span class="pill fp">future-purchases ${it.external_id || ""}</span>` : "typed here"],
      ["Funding", f ? `${f.goal} covers ${money(f.covered)} (${Math.round(f.pct * 100)}%)${f.short ? ", short " + money(f.short) : ""}` : (it.goal_id ? "fund set" : '<span class="pill none">no fund</span>')],
      ["Placed", it.month ? lab(it.month) + (it.day_known ? " · " + it.anchor_date : "") : "not yet"],
    ];
    if (it.month && it.net !== null) rows.push(["Month net with it", `<span class="num ${it.net < 0 ? "neg" : "pos"}">${money(it.net, true)}</span>`]);
    $("#detail").innerHTML =
      `<div class="row"><b>${it.name}</b><span class="num">${money(it.amount)}</span></div>` +
      rows.map(([k, v]) => `<div class="row"><span class="muted">${k}</span><span>${v}</span></div>`).join("") +
      `<div><div class="muted">${it.month ? "Move to" : "Place in"}</div><div class="moves">` +
      P.months.map((m) => { const after = netOf[m.month] - (m.month === it.month ? 0 : it.amount);
        return `<button type="button" data-move="${m.month}" class="${m.month === it.month ? "cur" : ""}">${lab(m.month)}${after < 0 ? " ⚠" : ""}</button>`; }).join("") +
      (it.month ? `<button type="button" data-move="">unplace</button>` : "") + `</div></div>` +
      `<div class="moves"><button type="button" id="d-edit">Edit</button><button type="button" id="d-done">Mark done</button><button type="button" id="d-del" class="danger">Delete</button></div>`;
    $("#detail").querySelectorAll("[data-move]").forEach((b) => b.addEventListener("click", async () => {
      try { await postJSON("/api/planning/flows/update", { id, month: b.dataset.move || null }); location.reload(); }
      catch (e) { alert("Could not move: " + e.message); }
    }));
    $("#d-edit").addEventListener("click", () => openForm(it));
    $("#d-done").addEventListener("click", async () => {
      try { await postJSON(`/api/planning/flows/${id}/done`); location.reload(); } catch (e) { alert("Could not mark done: " + e.message); }
    });
    $("#d-del").addEventListener("click", async () => {
      if (!confirm("Delete this planned spend? Recovery is manual (deletions log).")) return;
      try { await postJSON("/api/planning/flows/delete", { id }); location.reload(); } catch (e) { alert("Could not delete: " + e.message); }
    });
  }
  document.addEventListener("click", (e) => { const el = e.target.closest(".pin[data-id], .chip[data-id]"); if (el) showDetail(el.dataset.id); });

  // add / edit form
  const card = $("#add-card"), form = $("#flow-form"), status = $("#fl-status");
  const F = { id: $("#fl-id"), name: $("#fl-name"), group: $("#fl-group"), amount: $("#fl-amount"), cadence: $("#fl-cadence"),
              month: $("#fl-month"), anchor_date: $("#fl-date"), goal_id: $("#fl-goal"), notes: $("#fl-notes") };
  function openForm(it) {
    card.hidden = false;
    F.id.value = it ? it.id : ""; F.name.value = it ? it.name : ""; F.group.value = it ? (it.group || "") : "";
    F.amount.value = it ? it.amount : ""; F.cadence.value = it ? it.cadence : "once";
    F.month.value = it && it.month ? it.month : ""; F.anchor_date.value = it && it.day_known && it.anchor_date ? it.anchor_date : "";
    F.goal_id.value = it ? (it.goal_id || "") : ""; F.notes.value = it ? (it.notes || "") : "";
    $("#add-title").textContent = it ? "Edit planned spend" : "Add planned spend";
    $("#fl-submit").textContent = it ? "Save changes" : "Add"; status.textContent = "";
    card.scrollIntoView({ block: "nearest" }); F.name.focus();
  }
  $("#add-open").addEventListener("click", () => openForm(null));
  $("#fl-cancel").addEventListener("click", () => { card.hidden = true; });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { name: F.name.value, group: F.group.value, amount: F.amount.value, cadence: F.cadence.value,
                   goal_id: F.goal_id.value, notes: F.notes.value };
    if (F.anchor_date.value) body.anchor_date = F.anchor_date.value; else body.month = F.month.value || null;
    status.textContent = "Saving…";
    try {
      if (F.id.value) await postJSON("/api/planning/flows/update", { id: F.id.value, ...body });
      else await postJSON("/api/planning/flows", body);
      location.reload();
    } catch (err) { status.textContent = "Error: " + err.message; }
  });
})();
