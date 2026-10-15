// makeGrid — the client wiring for an AG Grid Infinite-Row-Model page, shared by the
// ledger, balances, and sheets grids (symmetric partner to the server-side
// GridCollection). Config in, grid out: it owns the datasource fetch, infinite
// gridOptions, search debounce, add-row modal, delete-with-confirm, and
// optimistic-revert on a failed inline edit. Pages pass only what differs; the add/delete
// chrome is wired only when the page's template has it (#add-row / #row-modal /
// #delete-rows — the sheets workspace has none).
//
// cfg: {
//   base,           // endpoint base, e.g. "/api/transactions" (→ base, /row, /update, /delete)
//   columnDefs,     // AG Grid column defs (page-specific; may include custom cell editors)
//   addFields,      // field names to read from #row-form on add, e.g. ["Date","Amount",...]
//   focusField,     // form field to focus when the add-row modal opens
//   deleteNoun,     // singular noun in the delete confirm, e.g. "transaction"
//   rowsPath?,      // suffix for the block POST (sheets posts to base + "/rows"; default "")
//   defaultColDef?, // override the grid-wide column defaults
//   cellHandlers?,  // { [field]: (e, ctx) => {} } — override the default inline-update for a column
//   onSaved?,       // (ok, e, d) => {} — after each inline update persists (or reverts); d is the
//                   // server reply ({ok, error?}) or {ok:false, error:"network error"}
//   onReady?,       // (ctx) => {} — extra setup once the grid exists (ctx: { api, base, post })
// }
// Returns ctx { api, post, setBase, setColumns, setQuery } — the setters let a page swap
// the whole collection at runtime (the sheets workspace switches per <select>).

// Shared currency formatter for valueFormatter in columnDefs.
window.gridMoney = (p) =>
  p.value == null ? "" :
  p.value.toLocaleString("en-US", { style: "currency", currency: "USD" });

// A page restored from the browser's back/forward cache shows a stale snapshot — the
// category dropdown and grid rows are built once at load and won't reflect edits made on
// the Categories page in the meantime. Force a fresh fetch when the page is restored.
window.addEventListener("pageshow", (e) => { if (e.persisted) window.location.reload(); });

// --- Row drill-down: read-only view of the full row ------------------------
// Shared by every grid page (ledger, balances, sheets). Lazily builds one modal,
// fetches the full doc from `url`, and lists every field — including the internal
// `_`-prefixed ones the grid never shows as columns.
window.openDocDetail = function (url, title) {
  let modal = document.getElementById("doc-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "doc-modal";
    modal.className = "modal-backdrop";
    modal.hidden = true;
    modal.innerHTML =
      '<div class="modal modal-wide" role="dialog" aria-modal="true" aria-labelledby="doc-modal-title">' +
      '  <div class="modal-head"><h3 id="doc-modal-title">Record</h3>' +
      '    <button type="button" class="modal-close" id="doc-close" aria-label="Close">×</button></div>' +
      '  <div id="doc-body" class="doc-detail"></div>' +
      "</div>";
    document.body.appendChild(modal);
    const close = () => { modal.hidden = true; };
    modal.querySelector("#doc-close").addEventListener("click", close);
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) close(); });
  }
  const titleEl = modal.querySelector("#doc-modal-title");
  const body = modal.querySelector("#doc-body");
  titleEl.textContent = title || "Record";
  body.innerHTML = '<p class="muted">Loading…</p>';
  modal.hidden = false;

  fetch(url)
    .then((r) => r.json())
    .then((d) => {
      if (!d.doc) { body.innerHTML = '<p class="muted">Not found.</p>'; return; }
      const dl = document.createElement("dl");
      dl.className = "doc-fields";
      Object.keys(d.doc).forEach((k) => {
        const dt = document.createElement("dt");
        dt.textContent = k;
        if (k.startsWith("_")) dt.className = "internal";
        const dd = document.createElement("dd");
        const v = d.doc[k];
        if (v == null) { dd.innerHTML = '<span class="muted">—</span>'; }
        else if (typeof v === "object") {
          const pre = document.createElement("pre");
          pre.textContent = JSON.stringify(v, null, 2);
          dd.appendChild(pre);
        } else { dd.textContent = String(v); }
        dl.appendChild(dt); dl.appendChild(dd);
      });
      body.innerHTML = "";
      body.appendChild(dl);
      body.scrollTop = 0;
    })
    .catch(() => { body.innerHTML = '<p class="muted">Failed to load.</p>'; });
};

// The sheet's left margin: a narrow pinned column holding one "open record" mark per
// row (base+"/doc/"+id is the endpoint). It is styled as a margin, not a column — no
// header, no pinned border — and the mark only takes its full color on row hover.
const OPEN_RECORD_ICON =
  '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false">' +
  '<path d="M7 1h4v4M11 1 6.5 5.5M5 11H1V7M1 11l4.5-4.5" fill="none" stroke="currentColor" ' +
  'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

window.detailColumn = function (base, title) {
  return {
    headerName: "", colId: "_detail", width: 30, minWidth: 30, maxWidth: 30, pinned: "left",
    sortable: false, resizable: false, filter: false, editable: false, suppressMovable: true,
    cellClass: "margin-cell", headerClass: "margin-head",
    cellRenderer: (p) => {
      if (!p.data) return "";
      const b = document.createElement("button");
      b.type = "button"; b.className = "row-detail-btn";
      b.title = "Open record"; b.setAttribute("aria-label", "Open record");
      b.innerHTML = OPEN_RECORD_ICON;
      // Opening the record is not a row click: it must neither select the row nor fire
      // rowClicked (the ledger opens its suggestion panel on that).
      b.addEventListener("mousedown", (e) => e.stopPropagation());
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        window.openDocDetail(base + "/doc/" + encodeURIComponent(p.data._id), title);
      });
      return b;
    },
  };
};

window.makeGrid = function (cfg) {
  let currentQ = "";
  let base = cfg.base;

  const post = (url, body) =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());

  const datasource = {
    getRows: (params) => {
      post(base + (cfg.rowsPath || ""), {
        startRow: params.startRow,
        endRow: params.endRow,
        sortModel: params.sortModel,
        q: currentQ,
      })
        .then((d) => params.successCallback(d.rows, d.lastRow))
        .catch(() => params.failCallback());
    },
  };

  // Default inline edit: persist the one changed field, revert the cell on failure.
  // Columns that avoid `field` (sheets uses colId + bracket getters so dotted/spaced
  // names aren't read as paths) persist by colId instead.
  function plainUpdate(e) {
    const field = e.colDef.field || e.colDef.colId;
    post(base + "/update", { id: e.data._id, field, value: e.newValue })
      .then((d) => {
        if (!d.ok) e.node.setDataValue(field, e.oldValue);
        if (cfg.onSaved) cfg.onSaved(!!d.ok, e, d);
      })
      .catch(() => {
        e.node.setDataValue(field, e.oldValue);
        if (cfg.onSaved) cfg.onSaved(false, e, { ok: false, error: "network error" });
      });
  }

  const cellHandlers = cfg.cellHandlers || {};

  const gridOptions = {
    columnDefs: [window.detailColumn(base, cfg.detailTitle || "Record"), ...cfg.columnDefs],
    rowModelType: "infinite",
    cacheBlockSize: 100,
    blockLoadDebounceMillis: 150,
    defaultColDef: cfg.defaultColDef || { sortable: true, resizable: true },
    rowSelection: "multiple",
    getRowId: (p) => p.data._id,           // stable selection across lazy blocks
    datasource,
    onCellValueChanged: (e) => {
      const handler = cellHandlers[e.colDef.field];
      if (handler) { handler(e, { base, post, plainUpdate }); return; }
      // A derived/read-only column set programmatically (e.g. the Group cell the
      // Category cascade fills) re-fires this event. Don't treat that as a user edit
      // — persisting it issues a spurious /update whose revert flickers the cell.
      const ed = e.colDef.editable;
      const isEditable = typeof ed === "function" ? ed(e) : !!ed;
      if (isEditable) plainUpdate(e);
    },
  };

  const api = agGrid.createGrid(document.querySelector("#grid"), gridOptions);

  // Search box → debounced refetch from block 0.
  let t;
  const search = document.querySelector("#search");
  if (search) {
    search.addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { currentQ = e.target.value; api.refreshInfiniteCache(); }, 250);
    });
  }

  // Add-row modal — only on pages whose template ships it.
  const modal = document.querySelector("#row-modal");
  const form = document.querySelector("#row-form");
  const addBtn = document.querySelector("#add-row");
  if (modal && form && addBtn) {
    const rowStatus = document.querySelector("#row-status");
    const today = new Date().toISOString().slice(0, 10);

    const openModal = () => {
      form.reset();
      if (form.elements["Date"]) form.elements["Date"].value = today;   // default to today, editable
      rowStatus.textContent = "";
      modal.hidden = false;
      const focus = cfg.focusField && form.elements[cfg.focusField];
      if (focus) focus.focus();
    };
    const closeModal = () => { modal.hidden = true; };

    addBtn.addEventListener("click", openModal);
    document.querySelector("#row-close").addEventListener("click", closeModal);
    document.querySelector("#row-cancel").addEventListener("click", closeModal);
    modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeModal(); });

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const payload = {};
      cfg.addFields.forEach((f) => {
        const v = form.elements[f].value.trim();
        if (v !== "") payload[f] = v;
      });
      rowStatus.textContent = "Adding…";
      post(base + "/row", payload)
        .then((d) => {
          if (!d.ok) { rowStatus.textContent = "Error: " + (d.error || "failed"); return; }
          closeModal();
          api.refreshInfiniteCache();
        })
        .catch(() => { rowStatus.textContent = "Network error"; });
    });
  }

  // Delete selected — the button sleeps until something is selected and says how many;
  // then confirm, hard-delete (server logs them), refresh.
  const deleteBtn = document.querySelector("#delete-rows");
  if (deleteBtn) {
    const followSelection = () => {
      const n = api.getSelectedRows().length;
      deleteBtn.disabled = n === 0;
      deleteBtn.textContent = n ? `Delete ${n} selected` : "Delete selected";
    };
    followSelection();
    api.addEventListener("selectionChanged", followSelection);
    deleteBtn.addEventListener("click", () => {
      const ids = api.getSelectedRows().map((r) => r._id);
      if (!ids.length) return;
      if (!confirm(`Delete ${ids.length} ${cfg.deleteNoun}(s)? This is logged but not undoable in the UI.`)) return;
      post(base + "/delete", { ids })
        .then((d) => { if (d.ok) { api.deselectAll(); api.refreshInfiniteCache(); } });
    });
  }

  const ctx = {
    api, post,
    get base() { return base; },
    // Swap the endpoint base at runtime (the sheets workspace points at another collection).
    setBase: (b) => { base = b; },
    // Replace the columns (fresh detail column included) and refetch from block 0.
    setColumns: (colDefs, detailTitle) => {
      api.setGridOption("columnDefs",
        [window.detailColumn(base, detailTitle || cfg.detailTitle || "Record"), ...colDefs]);
      api.setGridOption("datasource", datasource);   // reset → refetch block 0
    },
    // Set the search scope without waiting for the input debounce (no refetch by itself).
    setQuery: (q) => { currentQ = q; },
  };
  if (cfg.onReady) cfg.onReady(ctx);
  return ctx;
};
