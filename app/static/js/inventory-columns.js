// Inventory column (Finder) view — fetches the Group→Category→Subcategory→Item tree from
// /api/inventory/tree and renders cascading columns: picking a row in one column fills the
// next and clears everything downstream; picking an item fills the detail pane. The search
// box re-fetches the tree with ?q= (filtered server-side so counts and values roll up) and
// re-selects the path that was open where it still exists.
(function () {
  const $ = (id) => document.getElementById(id);
  const cols = {
    group: $("ic-col-group"), category: $("ic-col-category"),
    subcategory: $("ic-col-subcategory"), item: $("ic-col-item"),
  };
  const detail = $("ic-detail");
  const summary = $("ic-summary");
  const qBox = $("ic-q");
  const selected = { group: null, category: null, subcategory: null, item: null };  // names

  const money = (v) =>
    (v < 0 ? "-$" : "$") + Math.abs(v || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Render a column of folder rows. `next` is the child key (e.g. "categories"); when set,
  // rows show a chevron and clicking drills into the next column. For leaf items `next` is
  // null and clicking opens the detail pane.
  function renderColumn(col, rows, childKey, onPick) {
    col.innerHTML = "";
    if (!rows || !rows.length) return;
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "ic-row";
      const meta = childKey
        ? '<span class="ic-meta">' + r.count + " · " + money(r.value) + "</span><span class=\"ic-chevron\">›</span>"
        : '<span class="ic-meta">' + money(r.value) + "</span>";
      row.innerHTML = '<span class="ic-label">' + esc(r.name) + "</span>" + meta;
      row.addEventListener("click", () => {
        col.querySelectorAll(".ic-row").forEach((e) => e.classList.remove("active"));
        row.classList.add("active");
        onPick(r);
      });
      col.appendChild(row);
    });
  }

  function clearFrom(level) {
    const order = ["category", "subcategory", "item"];
    const from = order.indexOf(level);
    if (from >= 0) order.slice(from).forEach((l) => (cols[l].innerHTML = ""));
    if (level !== "detailOnly") detail.innerHTML = '<div class="ic-empty">Select an item.</div>';
  }

  function showItem(it) {
    const f = it.fields || {};
    const val = (v) => {
      const s = String(v);
      return /^https?:\/\//i.test(s)
        ? '<a href="' + esc(s) + '" target="_blank" rel="noopener">' + esc(s) + "</a>"
        : esc(s);
    };
    const rows = Object.keys(f)
      .filter((k) => k !== "Item_Name" && k !== "Value")
      .map((k) => "<dt>" + esc(k) + "</dt><dd>" + val(f[k]) + "</dd>")
      .join("");
    const imgs = (it.images || [])
      .map((id) => '<img class="ic-img" src="/api/inventory/image/' + encodeURIComponent(id) + '" alt="" loading="lazy" />')
      .join("");
    const sheet = it.doc_id
      ? '<a class="btn-secondary ic-sheet" href="/inventory/' + encodeURIComponent(it.doc_id) + '/sheet">📄 Open sheet</a>'
      : "";
    detail.innerHTML =
      "<h3>" + esc(it.name) + "</h3>" +
      '<div class="ic-detail-val">' + money(it.value) + sheet + "</div>" +
      (imgs ? '<div class="ic-imgs">' + imgs + "</div>" : "") +
      "<dl>" + rows + "</dl>";
  }

  // The four pick handlers, each remembering its choice so a re-fetch can restore the path.
  function pickSubcategory(s) {
    selected.subcategory = s.name; selected.item = null;
    clearFrom("item");
    renderColumn(cols.item, s.items, null, (it) => { selected.item = it.id; showItem(it); });
  }
  function pickCategory(c) {
    selected.category = c.name; selected.subcategory = null; selected.item = null;
    clearFrom("subcategory");
    renderColumn(cols.subcategory, c.subcategories, "items", pickSubcategory);
  }
  function pickGroup(g) {
    selected.group = g.name; selected.category = null; selected.subcategory = null; selected.item = null;
    clearFrom("category");
    renderColumn(cols.category, g.categories, "subcategories", pickCategory);
  }

  // Re-open the remembered path on a fresh tree: walk down while each name still exists,
  // marking the row active; the first missing level clears everything below it.
  function reselect(d) {
    const activate = (col, name) => {
      const rows = [...col.querySelectorAll(".ic-row")];
      const row = rows.find((r) => r.querySelector(".ic-label").textContent === name);
      if (row) row.classList.add("active");
      return !!row;
    };
    const want = { ...selected };
    const g = d.groups.find((x) => x.name === want.group);
    if (!g || !activate(cols.group, g.name)) { clearFrom("category"); return; }
    selected.group = g.name;
    clearFrom("category");
    renderColumn(cols.category, g.categories, "subcategories", pickCategory);
    const c = g.categories.find((x) => x.name === want.category);
    if (!c || !activate(cols.category, c.name)) return;
    selected.category = c.name;
    renderColumn(cols.subcategory, c.subcategories, "items", pickSubcategory);
    const s = c.subcategories.find((x) => x.name === want.subcategory);
    if (!s || !activate(cols.subcategory, s.name)) return;
    selected.subcategory = s.name;
    renderColumn(cols.item, s.items, null, (it) => { selected.item = it.id; showItem(it); });
    const it = s.items.find((x) => x.id === want.item);
    if (!it || !activate(cols.item, it.name)) return;
    selected.item = it.id;
    showItem(it);
  }

  let seq = 0;
  function load(q) {
    const mine = ++seq;
    fetch("/api/inventory/tree" + (q ? "?q=" + encodeURIComponent(q) : ""))
      .then((r) => r.json())
      .then((d) => {
        if (mine !== seq) return;                       // a newer request superseded this one
        summary.textContent = d.grand.count + " items · " + money(d.grand.value);
        renderColumn(cols.group, d.groups, "categories", pickGroup);
        if (!d.groups.length) {
          cols.group.innerHTML = '<div class="ic-empty">' + (q ? "No items match." : "No items.") + "</div>";
          clearFrom("category");
          return;
        }
        reselect(d);
      })
      .catch(() => { cols.group.innerHTML = '<div class="ic-empty">Failed to load.</div>'; });
  }

  // Search: debounced re-fetch, the term kept in the URL as ?q= so a reload keeps it.
  function applyQ() {
    const q = qBox ? qBox.value.trim() : "";
    const u = new URL(window.location.href);
    if (q) u.searchParams.set("q", q); else u.searchParams.delete("q");
    history.replaceState(null, "", u.pathname + u.search + u.hash);
    load(q);
  }
  if (qBox) {
    let t;
    qBox.addEventListener("input", () => { clearTimeout(t); t = setTimeout(applyQ, 150); });
    qBox.addEventListener("search", applyQ);                       // the native clear (x)
    qBox.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && qBox.value) { e.stopPropagation(); qBox.value = ""; applyQ(); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "/") return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      e.preventDefault(); qBox.focus(); qBox.select();
    });
  }
  load(qBox ? qBox.value.trim() : "");
})();
