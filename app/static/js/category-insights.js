// Category Insights — three linked panels (Group → Category → Transactions) over
// /api/category-insights/data, with cascading filters. Clicking a Group row sets the
// Group filter; clicking a Category row sets the Category filter; both re-fetch so the
// downstream panels narrow (the Looker-style drill-down). Plain fetch + render.
(function () {
  const $ = (id) => document.getElementById(id);
  const money = (v) =>
    (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const amtClass = (v) => (v < 0 ? "neg" : v > 0 ? "pos" : "");

  const els = {
    start: $("ci-start"), end: $("ci-end"), group: $("ci-group"),
    category: $("ci-category"), q: $("ci-q"), reset: $("ci-reset"),
    grand: $("ci-grand"),
    groups: $("ci-groups"), cats: $("ci-cats"), txns: $("ci-txns"),
    groupCount: $("ci-group-count"), catCount: $("ci-cat-count"), txnCount: $("ci-txn-count"),
  };

  function params() {
    const p = new URLSearchParams();
    if (els.start.value) p.set("start", els.start.value);
    if (els.end.value) p.set("end", els.end.value);
    if (els.group.value) p.set("group", els.group.value);
    if (els.category.value) p.set("category", els.category.value);
    if (els.q.value.trim()) p.set("q", els.q.value.trim());
    return p.toString();
  }

  // Render a clickable totals panel (Group / Category). `selected` highlights the active row;
  // `onPick` toggles that dimension's filter.
  function renderTotals(container, rows, selected, onPick) {
    container.innerHTML = "";
    if (!rows.length) { container.innerHTML = '<div class="ci-empty">No matching rows.</div>'; return; }
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "ci-row" + (r.name === selected ? " active" : "");
      row.innerHTML =
        '<span class="ci-name">' + escapeHtml(r.name) + "</span>" +
        '<span class="ci-amt ' + amtClass(r.total) + '">' + money(r.total) + "</span>";
      row.addEventListener("click", () => onPick(r.name === selected ? "" : r.name));
      container.appendChild(row);
    });
  }

  function renderTxns(rows, count, limit) {
    els.txns.innerHTML = "";
    els.txnCount.textContent = count > limit ? `top ${limit} of ${count.toLocaleString()}` : `${count.toLocaleString()}`;
    if (!rows.length) { els.txns.innerHTML = '<div class="ci-empty">No matching transactions.</div>'; return; }
    rows.forEach((t) => {
      const row = document.createElement("div");
      row.className = "ci-row";
      row.innerHTML =
        '<span class="ci-txn-meta">' +
        '  <span class="ci-txn-desc">' + escapeHtml(t.description || "(no description)") + "</span>" +
        '  <span class="ci-txn-sub">' + (t.date || "") + " · " + escapeHtml(t.category) + "</span>" +
        "</span>" +
        '<span class="ci-amt ' + amtClass(t.amount) + '">' + money(t.amount) + "</span>";
      els.txns.appendChild(row);
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  let seq = 0;
  function load() {
    const mine = ++seq;
    fetch("/api/category-insights/data?" + params())
      .then((r) => r.json())
      .then((d) => {
        if (mine !== seq) return;                       // a newer request superseded this one
        els.grand.textContent = "Grand total: " + money(d.grand_total);
        els.groupCount.textContent = d.groups.length + " groups";
        els.catCount.textContent = d.categories.length + " categories";
        renderTotals(els.groups, d.groups, els.group.value, (v) => { els.group.value = v; els.category.value = ""; load(); });
        renderTotals(els.cats, d.categories, els.category.value, (v) => { els.category.value = v; load(); });
        renderTxns(d.transactions, d.txn_count, d.txn_limit);
      })
      .catch(() => { els.txns.innerHTML = '<div class="ci-empty">Failed to load.</div>'; });
  }

  // Wire controls. Selects/dates reload immediately; search debounces.
  [els.start, els.end, els.group, els.category].forEach((el) =>
    el.addEventListener("change", () => { if (el === els.group) els.category.value = ""; load(); }));
  let t;
  els.q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 250); });
  els.reset.addEventListener("click", () => {
    els.group.value = ""; els.category.value = ""; els.q.value = "";
    els.start.value = els.start.min; els.end.value = els.end.max; load();
  });

  load();
})();
