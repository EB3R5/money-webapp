// Projected P&L — click a planned cell to move the first item of that Group in that month;
// the picker names the months that would go negative. Every write posts JSON then reloads.
(function () {
  const $ = (s) => document.querySelector(s);
  const P = JSON.parse($("#plan-data").textContent);
  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || "request failed");
    return data;
  }
  const money = (v) => "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const lab = (ym) => MON[+ym.slice(5, 7) - 1] + " " + ym.slice(2, 4);
  const netOf = Object.fromEntries(P.months.map((m) => [m.month, m.net]));
  const box = $("#b-move"), label = $("#b-move-label"), sel = $("#b-move-to"), status = $("#b-move-status");
  let moving = null;

  document.querySelectorAll("td.cell[data-group]").forEach((td) => td.addEventListener("click", () => {
    const m = P.months.find((x) => x.month === td.dataset.month);
    const item = m && m.items.find((it) => (it.group || "Planned") === td.dataset.group);
    if (!item) return;
    moving = item;
    label.textContent = `Move “${item.name}” (${money(item.amount)}) from ${lab(m.month)} to`;
    sel.innerHTML = P.months.map((x) => {
      const after = netOf[x.month] - (x.month === m.month ? 0 : item.amount);
      return `<option value="${x.month}" ${x.month === m.month ? "selected" : ""}>${lab(x.month)}${after < 0 ? " (goes negative)" : ""}</option>`;
    }).join("") + `<option value="">unplace (back to the shelf)</option>`;
    status.textContent = ""; box.hidden = false; box.scrollIntoView({ block: "nearest" });
  }));
  $("#b-move-go").addEventListener("click", async () => {
    if (!moving) return;
    status.textContent = "Moving…";
    try { await postJSON("/api/planning/flows/update", { id: moving.id, month: sel.value || null }); location.reload(); }
    catch (e) { status.textContent = "Error: " + e.message; }
  });
  $("#b-move-cancel").addEventListener("click", () => { moving = null; box.hidden = true; });
})();
