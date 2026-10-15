// makeCardEditor — the client mirror of app/card_collection.py. One factory owns the
// modal open / dirty-diff save / reflect dance for every card page. A page calls it
// with its endpoints and two tiny adapters: amount(item) and subtitle(item).
//
//   Read   : cards grouped into sections (server-rendered)
//   Create : "Add" → blank modal → POST opts.createUrl (only if createUrl given)
//   Update : click a card → modal → POST opts.endpoint/{id} with CHANGED fields only,
//            so untouched fields are never overwritten (the dirty-diff that fixed the
//            wiped-Unit_Cost bug — see ADR-0007).
//   Delete : "Delete" → POST opts.deleteUrl (only if deleteUrl given)
//
// opts: { data, fields, idField, titleField, endpoint,
//         createUrl?, deleteUrl?, amount(item)->num|null, subtitle(item)->string,
//         rowSelector?    (default ".acct-card" — table pages pass their own),
//         reloadOnUpdate? (reload after a saved edit instead of patching the card
//                          in place — for pages whose values recompute server-side),
//         imagesEnabled?, documentsEnabled? (the per-item photo gallery / documents panel),
//         kitsEnabled?    (read-only Kits chips from item._kits, hidden when empty),
//         searchFields?   (instant search box over these fields; see applySearch),
//         extraActions?: [{ id, handler(currentId, statusEl, item) }],
//         onCreated?(d)   (after a create; default: reload without the search term),
//         onDeleted?()    (after a delete; default: reload) }
//
// window.searchTokens / window.searchHit come from search.js (loaded before this file): the
// one JS mirror of app/search.py, shared with the planning pages.

window.makeCardEditor = function (opts) {
  const fields = opts.fields || [];
  const byId = {};
  (opts.data || []).forEach((s) =>
    (s.entries || []).forEach((i) => { byId[i._id] = i; }));

  const modal = document.getElementById("card-modal");
  const form = document.getElementById("card-form");
  const titleEl = document.getElementById("card-modal-title");
  const idDisplay = document.getElementById("card-id-display");
  const statusEl = document.getElementById("card-status");
  const deleteBtn = document.getElementById("card-delete");
  const imagesBox = document.getElementById("card-images");
  const imageInput = document.getElementById("card-image-input");

  let currentId = null;   // null while creating
  let original = {};      // field snapshot for the dirty-diff on edit

  const fmtMoney = (v) => v == null ? "—"
    : (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

  const close = () => { modal.hidden = true; currentId = null; original = {}; statusEl.textContent = ""; };

  const openEdit = (id) => {
    const i = byId[id];
    if (!i) return;
    currentId = id;
    original = {};
    titleEl.textContent = i[opts.titleField] || "—";
    idDisplay.textContent = i[opts.idField] || "—";
    statusEl.textContent = "";
    if (deleteBtn) deleteBtn.hidden = false;
    fields.forEach((f) => {
      const v = i[f.name] == null ? "" : String(i[f.name]);
      const el = form.elements[f.name];
      if (el) el.value = v;
      original[f.name] = v;
    });
    renderImages(); renderDocuments(); renderKits(i._kits);
    if (opts.onModalOpen) opts.onModalOpen("edit", i, form);
    modal.hidden = false;
    const first = form.querySelector("input,textarea");
    if (first) first.focus();
  };

  const openCreate = () => {
    currentId = null;
    original = {};
    titleEl.textContent = "New";
    idDisplay.textContent = "(auto)";
    statusEl.textContent = "";
    if (deleteBtn) deleteBtn.hidden = true;
    fields.forEach((f) => { const el = form.elements[f.name]; if (el) el.value = ""; });
    renderImages(); renderDocuments(); renderKits(null);
    if (opts.onModalOpen) opts.onModalOpen("create", null, form);
    modal.hidden = false;
    const first = form.querySelector("input,textarea");
    if (first) first.focus();
  };

  const reflect = (item) => {
    const card = document.querySelector('.acct-card[data-id="' + CSS.escape(currentId) + '"]');
    if (!card) return;
    const nameEl = card.querySelector(".acct-name");
    if (nameEl) nameEl.textContent = item[opts.titleField] || "";
    const amtEl = card.querySelector(".acct-amount");
    if (amtEl) {
      const amt = opts.amount ? opts.amount(item) : null;
      amtEl.textContent = fmtMoney(amt);
      amtEl.classList.toggle("neg", (amt || 0) < 0);
    }
    const subEl = card.querySelector(".acct-cat");
    if (subEl && opts.subtitle) subEl.textContent = opts.subtitle(item) || "";
  };

  // --- Kits (ADR-0018): read-only chips, one per Kit the row belongs to ----------
  // Membership is edited only on the Kit page; here the row just says where it belongs.
  // The block is created lazily under the form grid (after a page's own facts block, if
  // one is there) and hidden when the row is in no Kit or the modal is creating.
  function renderKits(list) {
    if (!opts.kitsEnabled) return;
    let box = document.getElementById("card-kits");
    if (!box) {
      box = document.createElement("div");
      box.id = "card-kits"; box.className = "card-kits";
      const grid = form.querySelector(".acct-form-grid") || form.firstElementChild;
      const after = document.getElementById("card-meta") || grid;
      after.parentNode.insertBefore(box, after.nextSibling);
    }
    if (!list || !list.length) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    box.innerHTML = '<span class="card-images-label muted">Kits</span>' + list.map((k) => {
      const a = document.createElement("a");
      a.className = "card-kit"; a.href = "/kits/" + encodeURIComponent(k.id); a.textContent = k.name;
      return a.outerHTML;
    }).join("");
  }

  // --- per-item images (gallery + upload), only when the page enables them ----
  const imagesOn = opts.imagesEnabled && imagesBox;
  const imageUrl = (id) => opts.endpoint + "/image/" + encodeURIComponent(id);

  function renderImages() {
    if (!imagesOn) return;
    const item = currentId ? byId[currentId] : null;
    const imgs = (item && item._images) || [];
    imagesBox.innerHTML = "";
    imgs.forEach((im) => {
      const fig = document.createElement("span");
      fig.className = "card-image";
      const a = document.createElement("a");
      a.href = imageUrl(im.id); a.target = "_blank"; a.rel = "noopener";
      const img = document.createElement("img");
      img.src = imageUrl(im.id); img.alt = im.filename || "";
      a.appendChild(img); fig.appendChild(a);
      const del = document.createElement("button");
      del.type = "button"; del.className = "card-image-del"; del.textContent = "×"; del.title = "Remove image";
      del.addEventListener("click", () => removeImage(im.id));
      fig.appendChild(del);
      imagesBox.appendChild(fig);
    });
    // Upload needs a saved item (an id to attach to).
    const canUpload = !!currentId;
    const addBtn = document.getElementById("card-image-add");
    const hint = document.getElementById("card-image-hint");
    if (addBtn) addBtn.style.display = canUpload ? "" : "none";
    if (hint) hint.style.display = canUpload ? "none" : "";
    if (imageInput) imageInput.disabled = !canUpload;
  }

  function updateThumb(item) {
    const card = document.querySelector('.acct-card[data-id="' + CSS.escape(currentId) + '"]');
    const thumb = card && card.querySelector(".acct-thumb");
    if (!thumb) return;
    const imgs = item._images || [];
    thumb.innerHTML = imgs.length ? '<img src="' + imageUrl(imgs[0].id) + '" alt="" loading="lazy" />' : "";
    card.classList.toggle("has-thumb", imgs.length > 0);
  }

  function uploadImages(fileList) {
    if (!currentId || !fileList || !fileList.length) return;
    const fd = new FormData();
    [...fileList].forEach((f) => fd.append("files", f));
    statusEl.textContent = "Uploading…";
    fetch(opts.endpoint + "/" + encodeURIComponent(currentId) + "/images", { method: "POST", body: fd })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { statusEl.textContent = "Upload failed"; return; }
        const item = byId[currentId];
        item._images = (item._images || []).concat(d.images || []);
        statusEl.textContent = (d.images || []).length + " image(s) added";
        renderImages(); updateThumb(item);
      })
      .catch(() => { statusEl.textContent = "Upload error"; });
  }

  function removeImage(id) {
    if (!currentId || !confirm("Remove this image?")) return;
    fetch(opts.endpoint + "/" + encodeURIComponent(currentId) + "/images/delete", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { statusEl.textContent = "Delete failed"; return; }
        const item = byId[currentId];
        item._images = (item._images || []).filter((im) => im.id !== id);
        renderImages(); updateThumb(item);
      })
      .catch(() => { statusEl.textContent = "Delete error"; });
  }

  if (imagesOn) {
    const addBtn = document.getElementById("card-image-add");
    if (addBtn && imageInput) addBtn.addEventListener("click", () => imageInput.click());
    if (imageInput) imageInput.addEventListener("change", (e) => { uploadImages(e.target.files); e.target.value = ""; });
  }

  // --- per-item documents (notes + files), only when the page enables them -------
  const docsList = document.getElementById("card-docs");
  const docsOn = opts.documentsEnabled && docsList;
  const docInput = document.getElementById("card-doc-input");

  function docRow(d) {
    const li = document.createElement("li");
    li.className = "doc-row"; li.dataset.id = d.id; li.dataset.name = d.name;
    const when = d.edited_at ? " · " + d.edited_at.slice(0, 16).replace("T", " ") : "";
    const kind = document.createElement("span");
    kind.className = "doc-kind doc-kind-" + d.kind; kind.textContent = d.kind;
    const name = document.createElement("a");
    name.className = "doc-name"; name.href = "/documents/" + encodeURIComponent(d.id); name.textContent = d.name;
    const meta = document.createElement("span");
    meta.className = "muted doc-meta"; meta.textContent = d.size + " B" + when;
    const actions = document.createElement("span");
    actions.className = "doc-actions";
    if (d.editable) {
      const edit = document.createElement("a");
      edit.className = "btn-link"; edit.href = "/documents/" + encodeURIComponent(d.id) + "?edit=1"; edit.textContent = "edit";
      actions.appendChild(edit);
    }
    ["rename", "delete"].forEach((act) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn-link doc-" + act; b.textContent = act;
      actions.appendChild(b);
    });
    li.append(kind, name, meta, actions);
    return li;
  }

  function renderDocuments() {
    if (!docsOn) return;
    const item = currentId ? byId[currentId] : null;
    const docs = (item && item._documents) || [];
    docsList.innerHTML = "";
    docs.forEach((d) => docsList.appendChild(docRow(d)));
    const count = document.getElementById("card-doc-count");
    const empty = document.getElementById("card-doc-empty");
    if (count) count.textContent = docs.length ? String(docs.length) : "";
    if (empty) empty.hidden = docs.length > 0 || !currentId;
    const canAttach = !!currentId;
    const hint = document.getElementById("card-doc-hint");
    ["card-doc-add", "card-doc-note"].forEach((id) => {
      const b = document.getElementById(id);
      if (b) b.hidden = !canAttach;
    });
    if (hint) hint.hidden = canAttach;
    if (docInput) docInput.disabled = !canAttach;
  }

  function uploadDocuments(fileList) {
    if (!currentId || !fileList || !fileList.length) return;
    const fd = new FormData();
    [...fileList].forEach((f) => fd.append("files", f, f.name));
    statusEl.textContent = "Uploading…";
    fetch(opts.endpoint + "/" + encodeURIComponent(currentId) + "/documents", { method: "POST", body: fd })
      .then((r) => r.json())
      .then((d) => {
        const item = byId[currentId];
        item._documents = (item._documents || []).concat(d.documents || []);
        statusEl.textContent = d.errors && d.errors.length ? "⚠ " + d.errors.join("; ")
          : (d.documents || []).length + " document(s) added";
        renderDocuments();
      })
      .catch(() => { statusEl.textContent = "Upload error"; });
  }

  if (docsOn) {
    const addDoc = document.getElementById("card-doc-add");
    if (addDoc && docInput) addDoc.addEventListener("click", () => docInput.click());
    if (docInput) docInput.addEventListener("change", (e) => { uploadDocuments(e.target.files); e.target.value = ""; });
    const noteBtn = document.getElementById("card-doc-note");
    if (noteBtn) noteBtn.addEventListener("click", () => {
      if (!currentId) return;
      const name = prompt("Note name:", "Note");
      if (name === null) return;
      fetch(opts.endpoint + "/" + encodeURIComponent(currentId) + "/notes", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
      })
        .then((r) => r.json())
        .then((d) => {
          if (!d.id) { statusEl.textContent = "Error: " + (d.error || "failed"); return; }
          window.location.href = "/documents/" + encodeURIComponent(d.id) + "?edit=1";
        })
        .catch(() => { statusEl.textContent = "Network error"; });
    });
    docsList.addEventListener("click", (e) => {
      const li = e.target.closest(".doc-row"); if (!li || !currentId) return;
      const id = li.dataset.id, item = byId[currentId];
      if (e.target.classList.contains("doc-delete")) {
        if (!confirm('Delete "' + li.dataset.name + '"? Logged but not undoable in the UI.')) return;
        post("/api/documents/" + encodeURIComponent(id) + "/delete", {}, () => {
          item._documents = (item._documents || []).filter((d) => d.id !== id);
          renderDocuments();
        });
      } else if (e.target.classList.contains("doc-rename")) {
        const name = prompt("Rename document:", li.dataset.name);
        if (name === null || !name.trim() || name.trim() === li.dataset.name) return;
        post("/api/documents/" + encodeURIComponent(id), { updates: { name: name.trim() } }, (res) => {
          item._documents = (item._documents || []).map((x) => (x.id === id && res.document) ? res.document : x);
          renderDocuments();
        });
      }
    });
  }

  function post(url, body, onOk) {
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { statusEl.textContent = "Error: " + (d.error || "failed"); return; }
        onOk(d);
      })
      .catch(() => { statusEl.textContent = "Network error"; });
  }

  // --- instant search, only when the page declares searchFields and ships the box ------
  // Matching rule mirrors app/search.py (up to 6 words, every word must match some field,
  // case-insensitive substring): keep the two in lockstep.
  const searchBox = document.getElementById("card-search");
  const searchOn = !!(opts.searchFields && opts.searchFields.length && searchBox);
  const searchTokens = window.searchTokens;
  const searchHit = (item, toks) => window.searchHit(opts.searchFields, item, toks);
  const round2 = (v) => Math.round(v * 100) / 100;

  function applySearch() {
    if (!searchOn) return;
    const q = searchBox.value.trim(), toks = searchTokens(q);
    let shown = 0, total = 0;
    document.querySelectorAll(".acct-section").forEach((sec) => {
      let secShown = 0, secTotal = 0;
      sec.querySelectorAll(".acct-card").forEach((card) => {
        const item = byId[card.dataset.id];
        const hit = !toks.length || (!!item && searchHit(item, toks));
        card.hidden = !hit;
        if (hit) { secShown++; secTotal += (item && item._amount) || 0; }
      });
      sec.hidden = secShown === 0;
      const tot = sec.querySelector(".acct-section-total");
      if (tot) tot.textContent = fmtMoney(round2(secTotal));
      shown += secShown; total += secTotal;
    });
    const countEl = document.getElementById("card-count"), grandEl = document.getElementById("card-grand");
    if (countEl) countEl.textContent = String(shown);
    if (grandEl) grandEl.textContent = fmtMoney(round2(total));
    const none = document.getElementById("card-no-match");
    if (none) none.hidden = shown > 0 || !toks.length;
    const u = new URL(window.location.href);
    if (q) u.searchParams.set("q", q); else u.searchParams.delete("q");
    history.replaceState(null, "", u.pathname + u.search + u.hash);
    // Links that rebuild the page (a group-by toggle) carry the term along.
    document.querySelectorAll(".group-toggle a").forEach((a) => {
      const l = new URL(a.getAttribute("href"), window.location.href);
      if (q) l.searchParams.set("q", q); else l.searchParams.delete("q");
      a.setAttribute("href", l.pathname + l.search);
    });
  }
  // A reload that must show a brand-new card (create) drops the term first.
  const reloadWithoutSearch = () => {
    const u = new URL(window.location.href);
    u.searchParams.delete("q");
    window.location.replace(u.pathname + u.search + u.hash);
  };
  if (searchOn) {
    let searchTimer;
    searchBox.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(applySearch, 150); });
    searchBox.addEventListener("search", applySearch);            // the native clear (x) button
    searchBox.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && searchBox.value) { e.stopPropagation(); searchBox.value = ""; applySearch(); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "/" || !modal.hidden) return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      e.preventDefault(); searchBox.focus(); searchBox.select();
    });
    applySearch();   // honour ?q= on load (the server pre-fills the box)
  }

  // Open affordances. Cards are <div role="button"> so a link_field ↗ can nest inside:
  // that click opens the link only, and Enter/Space mirror a native button.
  document.querySelectorAll(opts.rowSelector || ".acct-card").forEach((c) => {
    c.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest(".acct-link")) return;
      openEdit(c.dataset.id);
    });
    c.addEventListener("keydown", (e) => {
      if (e.target !== c) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openEdit(c.dataset.id); }
    });
  });
  // Status filter: merge into the live URL so ?group= and ?q= ride along (CSP: no inline onchange).
  const statusSel = document.querySelector(".status-filter");
  if (statusSel) statusSel.addEventListener("change", () => {
    const u = new URL(window.location.href);
    u.searchParams.set("status", statusSel.value);
    window.location.href = u.href;
  });
  const addBtn = document.getElementById("card-add");
  if (addBtn && opts.createUrl) addBtn.addEventListener("click", openCreate);

  // Close affordances
  document.getElementById("card-close").addEventListener("click", close);
  document.getElementById("card-cancel").addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) close(); });

  // Delete — confirm, hard-delete (server logs it), reload for fresh totals.
  if (deleteBtn && opts.deleteUrl) deleteBtn.addEventListener("click", () => {
    if (currentId === null) return;
    const name = (byId[currentId] && byId[currentId][opts.titleField]) || "this item";
    if (!confirm('Delete "' + name + '"? Logged but not undoable in the UI.')) return;
    statusEl.textContent = "Deleting…";
    post(opts.deleteUrl, { ids: [currentId] }, () => (opts.onDeleted ? opts.onDeleted() : window.location.reload()));
  });

  // Page-specific extra actions (e.g. accounts' "Add to Balances").
  (opts.extraActions || []).forEach((a) => {
    const b = document.getElementById(a.id);
    if (b) b.addEventListener("click", () => a.handler(currentId, statusEl, byId[currentId]));
  });

  // Save — create or update.
  form.addEventListener("submit", (e) => {
    e.preventDefault();

    if (currentId === null) {
      if (!opts.createUrl) return;
      const payload = {};
      fields.forEach((f) => {
        const el = form.elements[f.name];
        if (!el) return;
        const v = el.value.trim();
        if (v !== "") payload[f.name] = v;
      });
      statusEl.textContent = "Adding…";
      post(opts.createUrl, payload, opts.onCreated || reloadWithoutSearch);
      return;
    }

    // Update: send only the fields the user actually changed (dirty-diff).
    const payload = {};
    fields.forEach((f) => {
      const v = form.elements[f.name].value;
      if (v.trim() !== (original[f.name] || "").trim()) payload[f.name] = v.trim();
    });
    if (Object.keys(payload).length === 0) { close(); return; }
    statusEl.textContent = "Saving…";
    post(opts.endpoint + "/" + encodeURIComponent(currentId), payload, () => {
      if (opts.reloadOnUpdate) { window.location.reload(); return; }
      const item = byId[currentId];
      Object.keys(payload).forEach((k) => { item[k] = payload[k]; });
      item._amount = opts.amount ? opts.amount(item) : item._amount;   // keep the search totals right
      reflect(item);
      applySearch();
      close();
    });
  });
};
