// Categorization — the Rules tab: an editable AG Grid over /api/rules/* (order, enabled,
// the five conditions, Category), with move up/down, an add-rule modal, delete-selected,
// the preview counts (Matches / Wins / Uncategorized, click for samples) and the
// "Test a transaction" form. Modelled on categories.js. The ML model tab is its own slice.
(function () {
  const CFG = window.CATEGORIZATION;
  const CATEGORIES = CFG.categories || [];
  const RULE_FIELDS = CFG.ruleFields || [];

  let api = null;
  let counts = {};              // {rule id: {matches, wins, uncategorized_wins, samples}} from the preview

  const $ = (sel) => document.querySelector(sel);
  const status = (txt) => { $("#rules-status").textContent = txt || ""; };
  const post = (url, body) =>
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                 body: JSON.stringify(body || {}) }).then((r) => r.json());
  const getJSON = (url) => fetch(url).then((r) => r.json());

  // --- tabs -------------------------------------------------------------------------
  let mlLoaded = false;
  document.querySelectorAll("#cat-tabs .ctx-tab").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#cat-tabs .ctx-tab").forEach((x) => x.classList.toggle("active", x === b));
      $("#tab-rules").hidden = b.dataset.tab !== "rules";
      $("#tab-ml").hidden = b.dataset.tab !== "ml";
      if (b.dataset.tab === "ml" && !mlLoaded) { mlLoaded = true; loadModel(); }
    }));

  // --- ML model tab: info + retrain (lazy: loaded the first time the tab opens) -------
  function loadModel() {
    $("#model-status").textContent = "Loading…";
    return getJSON("/api/ml/model").then((d) => {
      const m = d.model;
      $("#min-rows").textContent = d.min_train_rows;
      $("#conf-min").textContent = d.conf_min;
      document.querySelectorAll("#model-info td[data-k]").forEach((td) => {
        const v = m ? m[td.dataset.k] : null;
        td.textContent = v == null ? "—" : (td.dataset.k === "trained_at" ? String(v).replace("T", " ").slice(0, 19) : String(v));
      });
      if (m && d.trained) {
        $("#model-status").textContent = "Loaded";
      } else {
        const have = d.labelled_rows, need = d.min_train_rows;
        $("#model-status").textContent = have >= need
          ? `No model yet — ${have} categorized transactions are enough: retrain below.`
          : `No model yet — ${have} of the ${need} categorized transactions a retrain needs. Categorize more on the Ledger, then retrain below.`;
      }
    }).catch(() => { $("#model-status").textContent = "⚠ failed to load"; });
  }

  $("#retrain-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const body = {};
    ["start_date", "end_date"].forEach((k) => { const v = (f.elements[k].value || "").trim(); if (v) body[k] = v; });
    const accounts = (f.elements["accounts"].value || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (accounts.length) body.accounts = accounts;
    if (!confirm("Retrain the ML model from your categorized transactions? Takes a few minutes.")) return;
    const st = $("#retrain-status");
    st.textContent = "Retraining…";
    $("#retrain-btn").disabled = true;
    post("/api/ml/retrain", body).then((d) => {
      st.textContent = d.status === "success"
        ? `✓ Retrained: ${d.rows_trained} rows, ${d.n_categories} categories`
        : "⚠ " + (d.error || "failed");
      loadModel();
    }).catch(() => { st.textContent = "⚠ network error"; })
      .finally(() => { $("#retrain-btn").disabled = false; });
  });

  // --- Category cell editor: datalist over the known categories --------------------
  function DatalistEditor() {}
  DatalistEditor.prototype.init = function (params) {
    this.input = document.createElement("input");
    this.input.className = "cat-editor";
    this.input.value = params.value == null ? "" : params.value;
    let dl = document.getElementById("dl-rule-category");
    if (!dl) {
      dl = document.createElement("datalist"); dl.id = "dl-rule-category";
      CATEGORIES.forEach((v) => { const o = document.createElement("option"); o.value = v; dl.appendChild(o); });
      document.body.appendChild(dl);
    }
    this.input.setAttribute("list", "dl-rule-category");
  };
  DatalistEditor.prototype.getGui = function () { return this.input; };
  DatalistEditor.prototype.afterGuiAttached = function () { this.input.focus(); this.input.select(); };
  DatalistEditor.prototype.getValue = function () { return this.input.value.trim(); };

  // --- enabled: a checkbox that posts straight away -----------------------------------
  function EnabledRenderer() {}
  EnabledRenderer.prototype.init = function (params) {
    this.box = document.createElement("input");
    this.box.type = "checkbox";
    this.box.checked = !!params.value;
    this.box.title = "Enabled";
    this.box.addEventListener("change", () => {
      status("Saving…");
      post("/api/rules/update", { id: params.data._id, field: "enabled", value: this.box.checked })
        .then((d) => {
          if (!d.ok) { this.box.checked = !this.box.checked; status("⚠ " + (d.error || "failed")); return; }
          params.node.updateData(d.rule);
          status(d.rule.enabled ? "✓ enabled" : "✓ disabled");
        })
        .catch(() => { this.box.checked = !this.box.checked; status("⚠ network error"); });
    });
  };
  EnabledRenderer.prototype.getGui = function () { return this.box; };
  EnabledRenderer.prototype.refresh = function (params) { this.box.checked = !!params.value; return true; };

  // --- move up / down -------------------------------------------------------------------
  function MoveRenderer() {}
  MoveRenderer.prototype.init = function (params) {
    this.el = document.createElement("span");
    this.el.className = "rule-move";
    [["▲", "up"], ["▼", "down"]].forEach(([glyph, direction]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = glyph; b.title = "Move " + direction;
      b.addEventListener("click", () => {
        status("Moving…");
        post("/api/rules/move", { id: params.data._id, direction })
          .then((d) => { if (!d.ok) { status("⚠ " + (d.error || "failed")); return; } loadRules(); })
          .catch(() => status("⚠ network error"));
      });
      this.el.appendChild(b);
    });
  };
  MoveRenderer.prototype.getGui = function () { return this.el; };
  MoveRenderer.prototype.refresh = function () { return true; };

  // --- grid ---------------------------------------------------------------------------
  const columnDefs = [
    { headerName: "", checkboxSelection: true, headerCheckboxSelection: true, width: 44,
      pinned: "left", sortable: false, resizable: false, editable: false },
    { field: "order", headerName: "#", width: 70, sort: "asc", editable: false },
    { field: "enabled", headerName: "On", width: 70, editable: false, cellRenderer: EnabledRenderer },
    { headerName: "Move", width: 80, editable: false, sortable: false, cellRenderer: MoveRenderer },
    ...RULE_FIELDS.map((f) => ({
      field: f, editable: true, flex: 1, minWidth: 140, cellClass: "editable-cell",
      cellEditor: "agTextCellEditor",
    })),
    { field: "Category", editable: true, flex: 1, minWidth: 150, cellClass: "editable-cell",
      cellEditor: DatalistEditor },
    { field: "issues", headerName: "Issues", flex: 1, minWidth: 140, editable: false, cellClass: "rule-issues",
      valueFormatter: (p) => (p.value || []).join(", ") },
    ...[["matches", "Matches", "Transactions this rule matches on its own (disabled rules included)"],
        ["wins", "Wins", "Transactions where this rule fires first (enabled rules only)"],
        ["uncategorized_wins", "Uncategorized", "Wins on blank-Category rows: what Apply rules would write"]]
      .map(([key, header, tip]) => ({
        colId: key, headerName: header, headerTooltip: tip, width: 120, editable: false,
        cellClass: "rule-count", type: "rightAligned",
        valueGetter: (p) => (counts[p.data._id] || {})[key],
        onCellClicked: (p) => showSamples(p.data._id, header),
      })),
  ];

  api = agGrid.createGrid($("#grid"), {
    columnDefs,
    rowData: [],
    defaultColDef: { sortable: true, resizable: true },
    rowSelection: "multiple",
    suppressRowClickSelection: true,
    getRowId: (p) => p.data._id,
    rowClassRules: { "rule-inactive": (p) => p.data && !p.data.active },
    onCellValueChanged: onEdit,
  });

  function onEdit(e) {
    const field = e.colDef.field;
    status("Saving…");
    post("/api/rules/update", { id: e.data._id, field, value: e.newValue })
      .then((d) => {
        if (!d.ok) { e.node.setDataValue(field, e.oldValue); status("⚠ " + (d.error || "failed")); return; }
        e.node.updateData(d.rule);
        status("✓ saved");
      })
      .catch(() => { e.node.setDataValue(field, e.oldValue); status("⚠ network error"); });
  }

  function loadRules() {
    return getJSON("/api/rules").then((d) => {
      api.setGridOption("rowData", d.rules || []);
      status(`${(d.rules || []).length} rule(s)`);
    }).then(loadPreview);
  }

  // --- preview counts (one server-side scan; loaded after the grid) -------------------
  function loadPreview() {
    status("Counting…");
    return getJSON("/api/rules/preview?samples=5").then((d) => {
      counts = d.rules || {};
      api.refreshCells({ columns: ["matches", "wins", "uncategorized_wins"], force: true });
      status(`${d.scanned} transactions scanned · ${d.blank_unmatched} uncategorized match no rule`);
    }).catch(() => status("⚠ counts failed"));
  }

  function showSamples(id, header) {
    const box = $("#rule-samples");
    const rows = (counts[id] || {}).samples || [];
    box.innerHTML = "";
    if (!rows.length) { box.textContent = "No matching transactions."; return; }
    const table = document.createElement("table");
    table.className = "rule-samples-table";
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      [[r.Date || "", ""], [r.Description || "", ""], [r.Amount == null ? "" : Number(r.Amount).toFixed(2), "num"],
       [r.Category || "—", ""]].forEach(([txt, cls]) => {
        const td = document.createElement("td"); td.textContent = txt; if (cls) td.className = cls; tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    const cap = document.createElement("div");
    cap.className = "muted";
    cap.textContent = `${header}: first ${rows.length} of ${(counts[id] || {}).matches || 0} matches`;
    box.appendChild(cap);
    box.appendChild(table);
  }

  // --- test a transaction ---------------------------------------------------------------
  $("#rule-test-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const body = {};
    ["Description", "Account", "Institution", "Amount"].forEach((k) => { body[k] = (f.elements[k].value || "").trim(); });
    const ruleEl = $("#rule-test-rule"), mlEl = $("#rule-test-ml");
    ruleEl.textContent = "…"; mlEl.textContent = "…";
    post("/api/rules/test", body).then((d) => {
      if (d.ok === false) { ruleEl.textContent = "⚠ " + (d.error || "failed"); mlEl.textContent = "—"; return; }
      ruleEl.innerHTML = "";
      if (d.rule) {
        const hit = document.createElement("div");
        hit.className = "rule-hit";
        const conds = Object.entries(d.rule.conditions || {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
        hit.textContent = `Rule #${d.rule.order} → ${d.rule.category}` + (conds ? ` (${conds})` : "");
        ruleEl.appendChild(hit);
      } else {
        ruleEl.textContent = "No rule matches.";
      }
      const preds = d.ml || [];
      mlEl.textContent = preds.length
        ? preds.map((p) => `${p.category} ${Math.round((p.confidence || 0) * 100)}%`).join(" · ")
        : "No suggestion.";
    }).catch(() => { ruleEl.textContent = "⚠ network error"; });
  });

  // --- add rule ---------------------------------------------------------------------
  const modal = $("#row-modal");
  const form = $("#row-form");
  const FORM_FIELDS = ["Category", ...RULE_FIELDS];

  function openAdd() {
    const wrap = $("#row-fields");
    wrap.innerHTML = "";
    FORM_FIELDS.forEach((col) => {
      const label = document.createElement("label");
      label.className = "field";
      const span = document.createElement("span"); span.textContent = col;
      const input = document.createElement("input");
      input.type = "text"; input.name = col;
      if (col === "Category") {
        let dl = document.getElementById("addl-rule-category");
        if (!dl) {
          dl = document.createElement("datalist"); dl.id = "addl-rule-category";
          CATEGORIES.forEach((v) => { const o = document.createElement("option"); o.value = v; dl.appendChild(o); });
          document.body.appendChild(dl);
        }
        input.setAttribute("list", "addl-rule-category");
      }
      label.appendChild(span); label.appendChild(input);
      wrap.appendChild(label);
    });
    $("#row-status").textContent = "";
    modal.hidden = false;
    form.elements["Category"].focus();
  }
  const closeAdd = () => { modal.hidden = true; };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const payload = {};
    FORM_FIELDS.forEach((col) => {
      const v = (form.elements[col].value || "").trim();
      if (v !== "") payload[col] = v;
    });
    $("#row-status").textContent = "Adding…";
    post("/api/rules/row", payload).then((d) => {
      if (!d.ok) { $("#row-status").textContent = "Error: " + (d.error || "failed"); return; }
      closeAdd();
      loadRules();
    }).catch(() => { $("#row-status").textContent = "Network error"; });
  });

  // --- delete -----------------------------------------------------------------------
  function deleteSelected() {
    const rows = api.getSelectedRows();
    if (!rows.length) { alert("Select one or more rules first."); return; }
    if (!confirm(`Delete ${rows.length} rule(s)? Logged, not undoable in the UI.`)) return;
    (async () => {
      let n = 0;
      for (const r of rows) {
        const d = await post("/api/rules/delete", { id: r._id });
        if (d.ok) n++;
      }
      status(`✓ deleted ${n}`);
      loadRules();
    })();
  }

  // --- wiring -----------------------------------------------------------------------
  $("#add-rule").addEventListener("click", openAdd);
  $("#row-close").addEventListener("click", closeAdd);
  $("#row-cancel").addEventListener("click", closeAdd);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeAdd(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeAdd(); });
  $("#delete-rules").addEventListener("click", deleteSelected);
  $("#preview-btn").addEventListener("click", loadPreview);

  loadRules();
})();
