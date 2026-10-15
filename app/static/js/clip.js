// The clip popup every clipper shares (clip.html). A bookmarklet (app/inventory_clip.py,
// app/software_clip.py) opens this page with the harvested payload base64url-encoded in
// the URL fragment; window.CLIP (slug, heading, noun, fields, board URL, …) says which
// board it serves. This script:
//   1. decodes the payload and POSTs it to /api/<slug>/clip/prepare (normalised fields,
//      the matching row, category suggestion, category list, and for software the
//      registry-owned facts),
//   2. picks a mode — update the matched row, search for one, or add new,
//   3. renders a per-field table (current vs scraped, tick what to apply) plus an
//      image gallery to attach,
//   4. saves through the board's own endpoints (dirty-diff: only ticked fields are
//      sent), then /api/<slug>/{id}/facts when the board has one, then
//      /api/<slug>/{id}/fetch-image for ticked images.
// Nothing is written until Apply. The named popup is reused by the bookmarklet, so a
// hashchange re-runs the whole flow.
(function () {
  const $ = (id) => document.getElementById(id);
  const CLIP = window.CLIP;
  const API = "/api/" + CLIP.slug;
  const N = CLIP.noun;                                  // "Item" / "software item"
  const LABELS = Object.fromEntries(CLIP.fields.map((f) => [f.name, f.label]));
  const label = (f) => LABELS[f] || f.replace(/_/g, " ");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let payload = null, prep = null, mode = null, item = null;

  // --- payload -----------------------------------------------------------------
  function decodeHash() {
    const h = location.hash.replace(/^#/, "");
    if (!h) return null;
    try {
      const b64 = h.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((h.length + 3) % 4);
      return JSON.parse(decodeURIComponent(escape(atob(b64))));
    } catch (e) { return null; }
  }

  function notice(msg, err) {
    const el = $("clip-notice");
    el.hidden = !msg; el.textContent = msg || ""; el.classList.toggle("err", !!err);
  }

  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    let d = {};
    try { d = await r.json(); } catch (e) { /* non-JSON */ }
    if (r.status === 401) { d.ok = false; d.error = "Not logged in — log in to Money in this browser and click the bookmark again."; }
    return d;
  }

  // --- init --------------------------------------------------------------------
  async function init() {
    payload = decodeHash();
    prep = null; mode = null; item = null;
    $("clip-editor").hidden = true; $("clip-result").hidden = true; $("clip-picker").hidden = true;
    $("clip-source").hidden = true; $("clip-sub").textContent = "";
    if (!payload || !payload.url) {
      notice("No clip data — click the bookmark on a page to clip.");
      showPicker("Search a " + N + " to open it here", "");
      return;
    }
    notice("");
    $("clip-source").hidden = false;
    const a = $("clip-source-link"); a.href = payload.url; a.textContent = payload.domain || payload.url;
    prep = await postJSON(API + "/clip/prepare", payload);
    if (!prep.ok) { notice(prep.error || "Could not prepare the clip.", true); return; }
    $("clip-sub").textContent = prep.scraped[CLIP.titleField] || "";
    if (prep.match) {
      selectItem(prep.match);
      if (prep.match_count > 1) notice(prep.match_count + " " + N + "s link to this page — " + prep.match[CLIP.idField] + " was picked. Use “Change…” if that's wrong.");
    } else {
      showPicker("No " + N + " links to this page yet. Is it one of these?", firstWords());
    }
  }

  // --- picker ------------------------------------------------------------------
  const firstWords = () => (prep.scraped[CLIP.titleField] || "").split(/\s+/).slice(0, 2).join(" ");
  let searchTimer = null;
  function showPicker(title, q) {
    $("clip-picker").hidden = false; $("clip-editor").hidden = true;
    $("clip-picker-title").textContent = title;
    $("clip-picker-hint").textContent = "";
    $("clip-add-new").hidden = !payload;
    const input = $("clip-q"); input.value = q || ""; input.focus();
    runSearch();
  }
  async function runSearch() {
    const q = $("clip-q").value.trim();
    const box = $("clip-results");
    if (!q) { box.innerHTML = ""; return; }
    const r = await fetch(API + "/items?q=" + encodeURIComponent(q));
    const d = r.ok ? await r.json() : { items: [] };
    box.innerHTML = d.items.length ? "" : '<div class="muted p-8">No ' + esc(N) + 's match.</div>';
    d.items.forEach((it) => {
      const div = document.createElement("div");
      div.className = "clip-hit";
      const sub = CLIP.subtitleField && it[CLIP.subtitleField];
      div.innerHTML = '<span class="id">' + esc(it[CLIP.idField] || it._id) + "</span><span>" + esc(it[CLIP.titleField] || "(unnamed)") +
        (sub ? ' <span class="meta">· ' + esc(sub) + "</span>" : "") + '</span><span class="meta">' + esc(it.Category || "") + "</span>";
      div.addEventListener("click", () => selectItem(it));
      box.appendChild(div);
    });
  }
  $("clip-q").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 200); });
  $("clip-add-new").addEventListener("click", () => { item = null; mode = "add"; render(); });

  function selectItem(it) {
    if (!payload) { window.location.href = CLIP.boardUrl; return; }   // no clip: just go to the board
    item = it; mode = "update"; render();
  }

  // --- table -------------------------------------------------------------------
  function render() {
    $("clip-picker").hidden = true; $("clip-editor").hidden = false; $("clip-result").hidden = true;
    const modeEl = $("clip-mode");
    if (mode === "update") {
      modeEl.innerHTML = "<b>Update</b> " + esc(item[CLIP.titleField] || "(unnamed)") + ' <span class="muted">(' + esc(item[CLIP.idField] || item._id) + ")</span>" +
        ' · <a href="#" id="clip-change">Change…</a> · <a href="#" id="clip-to-add">Add as new instead</a>';
      $("clip-change").addEventListener("click", (e) => { e.preventDefault(); showPicker("Which " + N + " is this?", $("clip-q").value || firstWords()); });
      $("clip-to-add").addEventListener("click", (e) => { e.preventDefault(); item = null; mode = "add"; render(); });
      $("clip-thead").innerHTML = "<th>Field</th><th>Current</th><th>From the page</th><th>Apply</th>";
    } else {
      modeEl.innerHTML = "<b>Add a new " + esc(N) + '</b> · <a href="#" id="clip-to-update">Update an existing ' + esc(N) + " instead…</a>";
      $("clip-to-update").addEventListener("click", (e) => { e.preventDefault(); showPicker("Which " + N + " is this?", firstWords()); });
      $("clip-thead").innerHTML = "<th>Field</th><th>Value</th><th>Include</th>";
    }
    const tb = $("clip-rows"); tb.innerHTML = "";
    CLIP.fields.forEach((fd) => tb.appendChild(row(fd.name, prep.scraped[fd.name] == null ? "" : prep.scraped[fd.name], fd.kind || "text", fd.options)));
    tb.appendChild(row("Category", (prep.category && prep.category.suggested) || "", "select"));
    if (mode === "add") (CLIP.addRows || []).forEach((r) => tb.appendChild(row(r.name, r.value || "", r.kind || "text")));
    renderImages();
    refresh();
  }

  function row(f, scraped, kind, options) {
    const tr = document.createElement("tr");
    tr.dataset.field = f;
    const cur = mode === "update" ? String(item[f] == null ? "" : item[f]).trim() : null;
    let editor;
    if (kind === "select" && options) {
      editor = '<select data-v><option value="">—</option>' + options.map((o) => '<option value="' + esc(o) + '"' + (o === String(scraped) ? " selected" : "") + ">" + esc(o) + "</option>").join("") + "</select>";
    } else if (kind === "select") {
      editor = '<select data-v>' + '<option value="">(no category)</option>' + categoryOptions(scraped) + "</select>";
    } else if (kind === "textarea") {
      editor = '<textarea data-v>' + esc(scraped) + "</textarea>";
    } else {
      editor = '<input type="text" data-v value="' + esc(scraped) + '" />';
    }
    tr.innerHTML = '<td class="f">' + esc(label(f)) + "</td>" +
      (mode === "update" ? '<td class="cur">' + (cur ? esc(cur) : '<span class="muted">—</span>') + "</td>" : "") +
      '<td class="new">' + editor + "</td>" +
      '<td class="apply"><input type="checkbox" data-apply /></td>';
    // Initial tick: the server's rule set. Refresh() re-derives it after edits.
    const cb = tr.querySelector("[data-apply]");
    const v = String(scraped).trim();
    if (mode === "update") {
      cb.checked = !!v && !cur;                 // fill blanks; conflicts opt-in
      if (f === "Link" && prep.link_same) cb.checked = false;
    } else {
      cb.checked = !!v;
    }
    cb.dataset.userSet = "";
    cb.addEventListener("change", () => { cb.dataset.userSet = "1"; refresh(); });
    // Editing the value re-derives the default tick unless the user already decided.
    const ed = tr.querySelector("[data-v]");
    ["input", "change"].forEach((ev) => ed.addEventListener(ev, () => {
      if (!cb.dataset.userSet) cb.checked = mode === "add" ? !!ed.value.trim() : !cur;
      refresh();
    }));
    return tr;
  }

  function categoryOptions(selected) {
    const groups = {};
    (prep.categories || []).forEach((c) => { (groups[c.Group || "(ungrouped)"] = groups[c.Group || "(ungrouped)"] || []).push(c._id); });
    if (selected && !(prep.categories || []).some((c) => c._id === selected)) (groups["(new)"] = groups["(new)"] || []).push(selected);
    return Object.keys(groups).sort().map((g) => '<optgroup label="' + esc(g) + '">' +
      groups[g].map((n) => '<option value="' + esc(n) + '"' + (n === selected ? " selected" : "") + ">" + esc(n) + "</option>").join("") + "</optgroup>").join("");
  }

  // Re-derive row states from the current editor values (the user may have edited a
  // scraped value or ticked a box); update the Apply button count.
  function refresh() {
    let n = 0;
    $("clip-rows").querySelectorAll("tr").forEach((tr) => {
      const f = tr.dataset.field, ed = tr.querySelector("[data-v]"), cb = tr.querySelector("[data-apply]");
      const v = ed.value.trim();
      const cur = mode === "update" ? String(item[f] == null ? "" : item[f]).trim() : "";
      const same = mode === "update" && (f === "Link" && prep.link_same && v === (prep.scraped.Link || "") ? true : v === cur);
      const empty = !v;
      tr.classList.toggle("dim", empty || same);
      tr.classList.toggle("diff", mode === "update" && !empty && !same && !!cur);
      cb.disabled = empty || same;
      if (cb.disabled) cb.checked = false;
      let tag = tr.querySelector(".same");
      if (same && !empty) { if (!tag) { tag = document.createElement("span"); tag.className = "same"; tag.textContent = " same"; tr.querySelector("td.new").appendChild(tag); } }
      else if (tag) tag.remove();
      if (cb.checked) n++;
    });
    const imgs = $("clip-images-new").querySelectorAll("input:checked").length;
    n += imgs;
    const btn = $("clip-apply");
    btn.disabled = n === 0;
    btn.textContent = mode === "update" ? (n ? "Apply " + n + " change" + (n === 1 ? "" : "s") : "Nothing to apply") : "Add " + N + (n ? " (" + n + ")" : "");
  }

  // --- images ------------------------------------------------------------------
  function renderImages() {
    const curWrap = $("clip-images-current-wrap"), cur = $("clip-images-current"), box = $("clip-images-new");
    cur.innerHTML = ""; box.innerHTML = "";
    const have = mode === "update" && item._images && item._images.length;
    curWrap.hidden = !(mode === "update");
    if (mode === "update") {
      if (have) item._images.forEach((im) => { cur.insertAdjacentHTML("beforeend", '<div class="clip-thumb"><img src="' + API + '/image/' + esc(im.id) + '" alt="" /></div>'); });
      else cur.innerHTML = '<span class="muted fs-12">none</span>';
    }
    const cands = prep.images || [];
    $("clip-images-hint").textContent = cands.length ? "" : "No images found on the page.";
    cands.forEach((u, i) => {
      const d = document.createElement("div");
      d.className = "clip-thumb";
      d.innerHTML = '<img src="' + esc(u) + '" alt="" referrerpolicy="no-referrer" /><label><input type="checkbox" value="' + esc(u) + '"' + (i === 0 && !have ? " checked" : "") + " /></label>";
      const cb = d.querySelector("input");
      const sync = () => d.classList.toggle("on", cb.checked);
      cb.addEventListener("change", () => { sync(); refresh(); });
      d.querySelector("img").addEventListener("error", () => { d.classList.add("bad"); cb.checked = false; refresh(); });
      sync();
      box.appendChild(d);
    });
  }

  // --- apply -------------------------------------------------------------------
  async function apply() {
    const btn = $("clip-apply"); btn.disabled = true;
    const status = $("clip-status"); status.textContent = "Saving…";
    const fields = {};
    $("clip-rows").querySelectorAll("tr").forEach((tr) => {
      const cb = tr.querySelector("[data-apply]");
      if (cb.checked && !cb.disabled) fields[tr.dataset.field] = tr.querySelector("[data-v]").value.trim();
    });
    const imageUrls = Array.from($("clip-images-new").querySelectorAll("input:checked")).map((i) => i.value);

    let docId, itemId, msg;
    if (mode === "update") {
      docId = item._id; itemId = item[CLIP.idField] || item._id;
      const n = Object.keys(fields).length;
      if (n) {
        const d = await postJSON(API + "/" + encodeURIComponent(docId), fields);
        if (!d.ok) { status.textContent = ""; notice("Save failed: " + (d.error || "unknown error"), true); btn.disabled = false; return; }
      }
      msg = "Updated " + esc(itemId) + " — " + n + " field" + (n === 1 ? "" : "s");
    } else {
      const d = await postJSON(API + "/row", fields);
      if (!d.ok) { status.textContent = ""; notice("Add failed: " + (d.error || "unknown error"), true); btn.disabled = false; return; }
      docId = d.id; itemId = d[CLIP.idField] || d.id;
      msg = "Added " + esc(itemId) + " — " + esc(fields[CLIP.titleField] || "(unnamed)");
    }
    // Registry-owned facts (software): stars, latest version, licence, repo… — the board's
    // own route decides what it keeps (never Status / Cost / Notes).
    if (CLIP.factsRoute && prep.facts && Object.keys(prep.facts).length) {
      status.textContent = "Saving facts…";
      const fr = await postJSON(API + "/" + encodeURIComponent(docId) + "/facts", prep.facts);
      if (fr.ok && fr.updated && fr.updated.length) msg += " · facts: " + esc(fr.updated.join(", "));
      else if (fr.ok === false && fr.error) msg += ' · <span class="fail">facts not saved: ' + esc(fr.error) + "</span>";
    }

    const list = $("clip-result-images"); list.innerHTML = "";
    let failed = 0;
    if (imageUrls.length) {
      status.textContent = "Attaching " + imageUrls.length + " image" + (imageUrls.length === 1 ? "" : "s") + "…";
      const d = await postJSON(API + "/" + encodeURIComponent(docId) + "/fetch-image", { image_urls: imageUrls, referer: payload.url });
      (d.results || []).forEach((r) => {
        const li = document.createElement("li");
        li.className = r.ok ? "ok" : "fail";
        li.textContent = (r.ok ? "✓ attached " : "✗ ") + r.url.replace(/^https?:\/\//, "").slice(0, 70) + (r.ok ? "" : " — " + (r.error || d.error || "failed"));
        list.appendChild(li);
        if (!r.ok) failed++;
      });
      if (!d.results) { failed = imageUrls.length; list.innerHTML = '<li class="fail">✗ ' + esc(d.error || "image fetch failed") + "</li>"; }
      const ok = imageUrls.length - failed;
      msg += " · " + ok + " image" + (ok === 1 ? "" : "s") + " attached" + (failed ? ", " + failed + " failed" : "");
    }
    status.textContent = "";
    showResult(docId, msg, failed > 0);
  }

  function showResult(docId, msg, showUpload) {
    $("clip-editor").hidden = true; $("clip-result").hidden = false;
    $("clip-result-msg").innerHTML = msg;
    $("clip-upload").hidden = !showUpload;
    wireUpload(docId);
  }

  // --- manual upload fallback (drag / paste / file) --------------------------------
  let uploadTarget = null;
  function wireUpload(docId) { uploadTarget = docId; }
  async function uploadFiles(files) {
    if (!uploadTarget || !files || !files.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => { if (f.type.startsWith("image/")) fd.append("files", f, f.name || "image.png"); });
    const r = await fetch(API + "/" + encodeURIComponent(uploadTarget) + "/images", { method: "POST", body: fd });
    const d = r.ok ? await r.json() : { ok: false };
    const li = document.createElement("li");
    li.className = d.ok ? "ok" : "fail";
    li.textContent = d.ok ? "✓ uploaded " + (d.images || []).length + " image" + ((d.images || []).length === 1 ? "" : "s") : "✗ upload failed";
    $("clip-result-images").appendChild(li);
  }
  const drop = $("clip-drop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", async (e) => {
    if (e.dataTransfer.files && e.dataTransfer.files.length) return uploadFiles(e.dataTransfer.files);
    // An image dragged from another tab arrives as a URL, not a file — fetch it server-side.
    const url = e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain");
    if (url && /^https?:\/\//.test(url) && uploadTarget) {
      const d = await postJSON(API + "/" + encodeURIComponent(uploadTarget) + "/fetch-image", { image_urls: [url.trim()], referer: payload && payload.url });
      const li = document.createElement("li"); li.className = d.ok ? "ok" : "fail";
      li.textContent = d.ok ? "✓ attached dropped image" : "✗ " + (d.error || "could not fetch dropped image");
      $("clip-result-images").appendChild(li);
    }
  });
  $("clip-file").addEventListener("change", (e) => uploadFiles(e.target.files));
  document.addEventListener("paste", (e) => {
    if ($("clip-result").hidden) return;
    const files = Array.from(e.clipboardData.items || []).filter((i) => i.kind === "file").map((i) => i.getAsFile());
    if (files.length) uploadFiles(files);
  });

  // --- wiring ----------------------------------------------------------------------
  $("clip-apply").addEventListener("click", apply);
  $("clip-cancel").addEventListener("click", () => window.close());
  $("clip-close").addEventListener("click", () => window.close());
  window.addEventListener("hashchange", init);
  init();
})();
