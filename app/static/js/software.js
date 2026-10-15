// Software adapter — feeds makeCardEditor the software endpoints. The card amount
// (monthly cost) is server-derived, so edits reload to re-group and re-total. The modal
// gains a read-only meta block (source key, install locations, latest version, stars)
// from the page overlay's `_meta`, the Link field an "open ↗", the Category field a
// datalist of the categories already on the board, and the page an import strip that
// posts an exporter's run file to /api/software/import.
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // Every item the page shipped, whatever shape window.CARD.data takes (map or sections).
  function allItems() {
    const data = window.CARD && window.CARD.data;
    if (!data) return [];
    const vals = Array.isArray(data) ? data : Object.values(data);
    return vals.flatMap((v) => (v && Array.isArray(v.entries)) ? v.entries : [v]).filter(Boolean);
  }

  function bindCategoryDatalist(form) {
    const el = form.elements["Category"]; if (!el) return;
    let dl = document.getElementById("category-list");
    if (!dl) { dl = document.createElement("datalist"); dl.id = "category-list"; document.body.appendChild(dl); }
    const names = [...new Set(allItems().map((i) => i.Category).filter(Boolean))].sort();
    dl.innerHTML = names.map((n) => '<option value="' + esc(n) + '">').join("");
    el.setAttribute("list", "category-list");
  }

  function bindFieldLink(form, item) {
    const span = form.querySelector('label[data-field="Link"] > span');
    if (!span) return;
    let a = span.querySelector(".field-link");
    const url = (item && item.Link) || "";
    if (/^https?:\/\//.test(url)) {
      if (!a) {
        a = document.createElement("a");
        a.className = "field-link"; a.target = "_blank"; a.rel = "noopener"; a.textContent = "open ↗";
        span.appendChild(a);
      }
      a.href = url; a.hidden = false;
    } else if (a) {
      a.hidden = true;
    }
  }

  // Read-only facts the importer / clipper own (not form fields, so a save never touches them).
  function renderMeta(form, meta) {
    let box = document.getElementById("card-meta");
    if (!box) {
      box = document.createElement("div");
      box.id = "card-meta"; box.className = "card-meta muted";
      const grid = form.querySelector(".acct-form-grid") || form.firstElementChild;
      grid.parentNode.insertBefore(box, grid.nextSibling);
    }
    if (!meta) { box.hidden = true; box.innerHTML = ""; return; }
    const rows = [];
    if (meta.version_latest) rows.push(["Latest", esc(meta.version_latest)]);
    if (meta.stars != null) rows.push(["Stars", "★ " + Number(meta.stars).toLocaleString("en-US")
      + (meta.topics && meta.topics.length ? " · " + esc(meta.topics.slice(0, 6).join(", ")) : "")]);
    if (meta.license_id) rows.push(["License", esc(meta.license_id)]);
    if (meta.repo_url) rows.push(["Repo", '<a href="' + esc(meta.repo_url) + '" target="_blank" rel="noopener">' + esc(meta.repo_url) + "</a>"]);
    if (meta.homepage && meta.homepage !== meta.repo_url) rows.push(["Homepage", '<a href="' + esc(meta.homepage) + '" target="_blank" rel="noopener">' + esc(meta.homepage) + "</a>"]);
    if (meta.bundle_id) rows.push(["Bundle", esc(meta.bundle_id)]);
    if (meta.archived) rows.push(["Archived", "yes — upstream repo is archived"]);
    (meta.install_locations || []).forEach((l) => {
      rows.push(["Installed", esc(l.host) + " · " + esc(l.manager) + ":" + esc(l.id)
        + (l.version ? " v" + esc(l.version) : "") + (l.seen_at ? " (seen " + esc(String(l.seen_at).slice(0, 10)) + ")" : "")]);
    });
    if (meta.refreshed_at) rows.push(["Refreshed", esc(String(meta.refreshed_at).slice(0, 16).replace("T", " "))]);
    if (meta.automatic_status) rows.push(["Status", "automatic — the next import may change it; edit it to take over"]);
    if (!rows.length) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    box.innerHTML = rows.map(([k, v]) => "<div><b>" + k + "</b><span>" + v + "</span></div>").join("");
  }

  makeCardEditor({
    ...window.CARD,
    endpoint: "/api/software",
    createUrl: "/api/software/row",
    deleteUrl: "/api/software/delete",
    amount: () => null,                    // monthly cost is derived server-side; reload reflects it
    subtitle: (i) => i.Kind || "",
    reloadOnUpdate: true,                  // Status / Cost / cadence edits change grouping + totals
    onModalOpen: (mode, item, form) => {
      bindCategoryDatalist(form);
      bindFieldLink(form, item);
      renderMeta(form, item && item._meta);
    },
  });

  // --- the import strip: a run file → POST /api/software/import -------------------
  const fileEl = document.getElementById("sw-import-file");
  const btn = document.getElementById("sw-import-btn");
  const status = document.getElementById("sw-import-status");
  if (fileEl && btn && status) {
    btn.addEventListener("click", () => {
      const f = fileEl.files && fileEl.files[0];
      if (!f) { status.textContent = "Choose the exported run (.json) first."; return; }
      status.textContent = "Importing…";
      f.text().then((txt) => {
        let body;
        try { body = JSON.parse(txt); } catch (e) { status.textContent = "Not valid JSON."; return; }
        return fetch("/api/software/import", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        }).then((r) => r.json()).then((d) => {
          if (d.status !== "ok") { status.textContent = d.error || "Import failed"; return; }
          status.textContent = d.host + ": " + d.added + " added · " + d.updated + " updated · "
            + d.unchanged + " unchanged · " + d.removed + " removed" + (d.skipped ? " · " + d.skipped + " skipped" : "");
          if (d.added || d.updated || d.removed) setTimeout(() => window.location.reload(), 900);
        });
      }).catch(() => { status.textContent = "Network error"; });
    });
  }
})();
