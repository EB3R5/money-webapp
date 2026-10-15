// Kit page island (ADR-0018, plan D6–D9). Three jobs:
//   1. the Kit's own fields through makeCardEditor (shared modal): "✎ Edit kit" opens the
//      current Kit, "＋ New kit" creates one and navigates to it, Delete returns to /kits,
//      a saved edit reloads (hero, sidebar and stats recompute server-side);
//   2. the How-to textarea gets a server-rendered preview (the Note renderer), debounced;
//   3. the transfer list: Available (filtered by the Search rule's JS mirror) ↔ In this kit,
//      each arrow click POSTs /api/kits/{id}/members and the page patches itself from the reply.
// csrf.js already stamps the token on every fetch. No inline handlers (CSP).
(function () {
  const K = window.KIT || {};
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const money = (v) => v == null ? "—" : "$" + Math.round(v).toLocaleString("en-US");
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) }).then((r) => r.json());

  // --- 1. the Kit itself ---------------------------------------------------------------
  let previewTimer;
  function howToPreview(form) {
    const ta = form.elements.How_To;
    if (!ta) return;
    const field = ta.closest(".field");
    let box = field.querySelector(".kit-howto-preview");
    if (!box) {
      box = document.createElement("div"); box.className = "kit-howto-preview kit-howto";
      field.appendChild(box);
      ta.addEventListener("input", () => { clearTimeout(previewTimer); previewTimer = setTimeout(render, 300); });
    }
    function render() {
      const body = ta.value;
      if (!body.trim()) { box.innerHTML = '<span class="muted">Preview — nothing written yet.</span>'; return; }
      post("/api/documents/render", { body }).then((d) => { box.innerHTML = d.html || ""; }).catch(() => {});
    }
    render();
  }
  if (window.makeCardEditor) {
    makeCardEditor({
      ...window.CARD,
      endpoint: "/api/kits",
      createUrl: "/api/kits/row",
      deleteUrl: "/api/kits/delete",
      rowSelector: ".kit-edit",
      reloadOnUpdate: true,
      amount: () => null,
      subtitle: () => "",
      onModalOpen: (mode, item, form) => howToPreview(form),
      onCreated: (d) => { window.location.href = "/kits/" + encodeURIComponent(d.id); },
      onDeleted: () => { window.location.href = "/kits"; },
    });
  }

  // --- 2 & 3. the transfer list ------------------------------------------------------------
  const availUl = $("kit-avail"), inUl = $("kit-in");
  if (!K.id || !availUl || !inUl) return;
  const q = $("kit-avail-q"), btnAdd = $("kit-add"), btnRemove = $("kit-remove"), status = $("kit-transfer-status");
  let members = K.members || [], available = K.available || [];
  const sel = { avail: new Set(), in: new Set() };

  const thumb = (m) => m.image ? `<img src="${m.image}" alt="" loading="lazy" />` : '<span class="kit-nophoto">—</span>';
  const badges = (m) => (m.table === "software" ? '<span class="kit-badge" title="Software">SW</span>' : "")
    + (m.status && !m.active ? `<span class="kit-badge kit-badge-status">${esc(m.status.replace(/_/g, " "))}</span>` : "");
  const amount = (m) => money(m.amount) + (m.table === "software" && m.amount ? "/mo" : "");
  const SEARCH_IDX = [0, 1, 2, 3];   // the row's `search` list (per-table fields chosen server-side)
  const hit = (m, toks) => window.searchHit(SEARCH_IDX, m.search, toks);

  function li(m, which) {
    const hint = which === "avail" && m.in_kits ? `<span class="muted">in ${m.in_kits} kit${m.in_kits === 1 ? "" : "s"}</span>` : "";
    return `<li data-key="${esc(m.key)}" class="${sel[which].has(m.key) ? "sel" : ""}" title="${esc(m.title)}">${thumb(m)}${badges(m)}<span class="t">${esc(m.title)}</span>${hint}<span class="muted amt">${amount(m)}</span></li>`;
  }
  function tile(m) {
    return `<figure class="kit-tile" data-key="${esc(m.key)}" title="${esc(m.title)}"><a href="${esc(m.href)}" class="kit-tile-link">${thumb(m)}<span class="kit-badges">${badges(m)}</span><figcaption>${esc(m.title)} · ${amount(m)}</figcaption></a>${m.link ? `<a class="acct-link kit-link" href="${esc(m.link)}" target="_blank" rel="noopener" title="Open link">↗</a>` : ""}</figure>`;
  }
  function statline(st) {
    return `${st.count} items · ${st.n_inv} inventory${st.n_sw ? ` · ${st.n_sw} software` : ""} · ${money(st.value)} value${st.monthly ? ` · ${money(st.monthly)}/mo` : ""}`;
  }

  function render() {
    const toks = window.searchTokens(q.value);
    const shown = available.filter((m) => !toks.length || hit(m, toks));
    availUl.innerHTML = shown.slice(0, 300).map((m) => li(m, "avail")).join("")
      + (shown.length > 300 ? `<li class="muted more">… ${shown.length - 300} more — filter to narrow</li>` : "")
      || '<li class="muted more">Nothing matches.</li>';
    $("kit-avail-count").textContent = shown.length === available.length ? `${available.length}` : `${shown.length} of ${available.length}`;
    inUl.innerHTML = members.map((m) => li(m, "in")).join("") || '<li class="muted more">Empty — select on the left and press →</li>';
    $("kit-in-count").textContent = members.length;
    btnAdd.disabled = !sel.avail.size; btnRemove.disabled = !sel.in.size;
  }
  function patchPage(d) {
    members = d.members; available = d.available;
    $("kit-grid").innerHTML = members.map(tile).join("");
    $("kit-no-members").hidden = members.length > 0;
    $("kit-member-count").textContent = d.stats.count + " items";
    $("kit-stats").textContent = statline(d.stats);
    const facts = $("kit-facts");
    if (facts) {
      const dd = facts.querySelectorAll("dd");
      dd[0].textContent = `${d.stats.n_inv} inventory${d.stats.n_sw ? `, ${d.stats.n_sw} software` : ""}`;
      dd[1].textContent = money(d.stats.value);
      dd[2].innerHTML = d.stats.monthly ? money(d.stats.monthly) + "/mo" : '<span class="muted">none</span>';
      dd[3].textContent = `${d.stats.with_photo} of ${d.stats.count}`;
    }
    const nav = document.querySelector(`.kits-nav a[data-kit="${CSS.escape(K.id)}"] .kits-nav-count`);
    if (nav) nav.textContent = d.stats.count;
    const hero = $("kit-hero"); let img = $("kit-cover");
    if (d.cover && !img) { img = document.createElement("img"); img.id = "kit-cover"; img.alt = ""; hero.prepend(img); }
    if (img && d.cover) img.src = d.cover; else if (img && !d.cover) img.remove();
  }
  // Selection toggles in place (no re-render), so a long list keeps its scroll and the
  // other rows stay where the eye left them.
  function toggle(which, ul) {
    ul.addEventListener("click", (e) => {
      const item = e.target.closest("li[data-key]"); if (!item) return;
      const k = item.dataset.key;
      if (sel[which].has(k)) sel[which].delete(k); else sel[which].add(k);
      item.classList.toggle("sel", sel[which].has(k));
      btnAdd.disabled = !sel.avail.size; btnRemove.disabled = !sel.in.size;
    });
  }
  async function move(add, remove) {
    status.textContent = "Saving…"; btnAdd.disabled = btnRemove.disabled = true;
    try {
      const d = await post(`/api/kits/${encodeURIComponent(K.id)}/members`, { add, remove });
      if (!d.ok) { status.textContent = "Error: " + (d.error || "failed"); render(); return; }
      sel.avail.clear(); sel.in.clear();
      patchPage(d); render();
      const n = (d.added || []).length + (d.removed || 0);
      status.textContent = n ? `✓ ${(d.added || []).length ? `added ${d.added.length}` : ""}${(d.added || []).length && d.removed ? ", " : ""}${d.removed ? `removed ${d.removed}` : ""}` : "Nothing changed";
    } catch (_) { status.textContent = "Network error"; render(); }
  }
  toggle("avail", availUl); toggle("in", inUl);
  q.addEventListener("input", render);
  q.addEventListener("search", render);
  btnAdd.addEventListener("click", () => move([...sel.avail], []));
  btnRemove.addEventListener("click", () => move([], [...sel.in]));
  render();
})();
