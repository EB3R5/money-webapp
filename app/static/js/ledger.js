// Ledger grid — config for makeGrid (app/static/js/grid-factory.js), plus the two
// transaction-specific bits: the autocomplete Category cell editor and the cascade
// that derives Group/etc when a category is picked.
(function () {
  // Fixed category list + a name→{Group,...} lookup so dependent fields can update the
  // instant a category is chosen.
  const categories = (window.LEDGER.categories || []);
  const categoryNames = categories.map((c) => c.Category);
  const DERIVED = ["Group", "Budget", "Cashflow Type", "Timing", "Type"];
  const gridCols = new Set(window.LEDGER.columns || []);   // fields that are real columns
  const catByName = Object.fromEntries(categories.map((c) => [c.Category, c]));

  // Typeable cell editor with autocomplete: native <input list> + <datalist>. AG Grid
  // Community has no rich-select, so this is a small custom editor.
  class CategoryEditor {
    init(params) {
      this.original = params.value == null ? "" : params.value;
      this.eGui = document.createElement("input");
      this.eGui.className = "cat-editor";
      this.eGui.setAttribute("list", "cat-options");
      this.eGui.value = this.original;
      if (!document.getElementById("cat-options")) {
        const dl = document.createElement("datalist");
        dl.id = "cat-options";
        categoryNames.forEach((n) => { const o = document.createElement("option"); o.value = n; dl.appendChild(o); });
        document.body.appendChild(dl);
      }
    }
    getGui() { return this.eGui; }
    afterGuiAttached() { this.eGui.focus(); this.eGui.select(); }
    getValue() { return this.eGui.value.trim() || this.original; }
    isPopup() { return false; }
  }

  // Amount typed into the grid: "$1,234.56", "-9.99", "(12.00)" → number; blank → null (a
  // manual row may have none). Anything else keeps the old value and says why, so a typo is
  // never saved as a blank amount (the server accepts null with ok:true).
  const saveStatus = () => document.getElementById("cat-status");
  function parseAmount(p) {
    const raw = String(p.newValue == null ? "" : p.newValue).trim();
    if (raw === "") return null;
    const neg = /^\(.*\)$/.test(raw);
    const n = Number(raw.replace(/[()$,\s]/g, ""));
    if (!Number.isFinite(n)) {
      const st = saveStatus();
      if (st) st.textContent = `Amount must be a number — kept ${window.gridMoney({ value: p.oldValue })}`;
      return p.oldValue;
    }
    return neg ? -Math.abs(n) : n;
  }

  const columnDefs = [
    { field: "Date", width: 130, sort: "desc", editable: true, cellClass: "editable-cell",
      checkboxSelection: true },
    { field: "Description", flex: 2, minWidth: 220, editable: true, cellClass: "editable-cell" },
    { field: "Category", flex: 1, minWidth: 140, editable: true, cellClass: "editable-cell",
      cellEditor: CategoryEditor },
    { field: "Group", width: 130, cellClass: "derived-cell" },   // derived from Category, not directly editable
    { field: "Amount", width: 130, type: "rightAligned", valueFormatter: window.gridMoney,
      editable: true, cellClass: "editable-cell money-col", headerClass: "money-col",
      valueParser: parseAmount,
      cellClassRules: { "neg": (p) => p.value < 0, "pos": (p) => p.value > 0 } },
    { field: "Account", flex: 1, minWidth: 140, editable: true, cellClass: "editable-cell" },
    { field: "Institution", flex: 1, minWidth: 140, editable: true, cellClass: "editable-cell" },
  ];

  // Category edit: optimistic derive of Group/etc, then reconcile with the server.
  function onCategoryChanged(e, ctx) {
    const setField = (f, v) => {
      if (!gridCols.has(f)) { e.data[f] = v; return; }
      if (e.data[f] === v) return;          // no-op: avoid a redundant cell re-render (flicker)
      e.node.setDataValue(f, v);
    };
    const prevDerived = {};
    const local = catByName[e.newValue] || {};
    DERIVED.forEach((f) => {
      prevDerived[f] = e.data[f];
      if (f in local) setField(f, local[f]);
    });
    const revert = () => {
      e.node.setDataValue("Category", e.oldValue);
      DERIVED.forEach((f) => setField(f, prevDerived[f]));
    };
    ctx.post(ctx.base + "/category", { id: e.data._id, value: e.newValue })
      .then((d) => {
        if (!d.ok) { console.error("category update failed", d); revert(); return; }
        DERIVED.forEach((f) => { if (d.derived && f in d.derived) setField(f, d.derived[f]); });
      })
      .catch(revert);
  }

  // Populate the add-row modal's category datalist once.
  const dl = document.createElement("datalist");
  dl.id = "row-cat-options";
  categoryNames.forEach((n) => { const o = document.createElement("option"); o.value = n; dl.appendChild(o); });
  document.body.appendChild(dl);

  // Write a category + its derived fields onto a grid row node (used when a Rule chip or
  // an ML suggestion is clicked in the panel).
  function applyToNode(node, category) {
    const local = catByName[category] || {};
    node.setDataValue("Category", category);
    DERIVED.forEach((f) => {
      const v = f in local ? local[f] : undefined;
      if (v === undefined) return;
      if (gridCols.has(f)) node.setDataValue(f, v);
      else node.data[f] = v;
    });
  }

  const money = (v) => v == null ? "" :
    Number(v).toLocaleString("en-US", { style: "currency", currency: "USD" });

  // --- suggestion panel: the Rule hit and the ML picks for the selected row ------
  // Nothing is written on a row click; each chip is an ordinary Category write.
  function wireSuggestPanel(ctx) {
    const panel = document.getElementById("suggest-panel");
    const descEl = document.getElementById("suggest-desc");
    const amtEl = document.getElementById("suggest-amount");
    const ruleEl = document.getElementById("suggest-rule");
    const mlEl = document.getElementById("suggest-ml");
    document.getElementById("suggest-close").addEventListener("click", () => { panel.hidden = true; });

    const note = (el, text) => { el.innerHTML = ""; const p = document.createElement("p"); p.className = "muted"; p.textContent = text; el.appendChild(p); };

    const chip = (e, category, label, extraClass) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pred-chip" + (extraClass ? " " + extraClass : "");
      btn.innerHTML = label;
      btn.addEventListener("click", () => {
        applyToNode(e.node, category);          // optimistic
        ctx.post(ctx.base + "/category", { id: e.data._id, value: category })
          .then((res) => { if (res.ok) panel.hidden = true; });
      });
      return btn;
    };

    ctx.api.addEventListener("rowClicked", (e) => {
      if (!e.data || !e.data._id) return;
      panel.hidden = false;
      descEl.textContent = e.data.Description || "(no description)";
      amtEl.textContent = money(e.data.Amount);
      note(ruleEl, "Loading…");
      note(mlEl, "Loading…");

      fetch(ctx.base + "/" + encodeURIComponent(e.data._id) + "/suggest")
        .then((r) => r.json())
        .then((d) => {
          ruleEl.innerHTML = "";
          if (d.rule) {
            const r = d.rule;
            ruleEl.appendChild(chip(e, r.category,
              '<span class="pred-cat"><span>Apply rule #' + (r.order == null ? "?" : r.order) +
              " → " + r.category + "</span></span>", "pred-rule"));
          } else {
            note(ruleEl, "No rule matches.");
          }
          mlEl.innerHTML = "";
          const preds = d.ml || [];
          if (d.model === false) { note(mlEl, "No model yet — retrain on the Categorization page."); return; }
          if (!preds.length) { note(mlEl, "No suggestion."); return; }
          preds.forEach((p) => {
            const pct = Math.round((p.confidence || 0) * 100);
            const el = chip(e, p.category,
              '<span class="pred-cat"><span>' + p.category + "</span><span>" + pct + "%</span></span>" +
              '<span class="pred-bar"></span>');
            el.querySelector(".pred-bar").style.width = pct + "%";   // CSSOM, not a style attribute (CSP)
            mlEl.appendChild(el);
          });
        })
        .catch(() => { note(ruleEl, "Failed to load."); note(mlEl, ""); });
    });
  }

  // --- toolbar: Rule apply and ML suggest, each its own batch ----------------------
  function wireToolbar(ctx) {
    const status = document.getElementById("cat-status");

    document.getElementById("apply-rules-btn").addEventListener("click", () => {
      if (!confirm("Apply the Rules to every uncategorized transaction?")) return;
      status.textContent = "Applying rules…";
      ctx.post("/api/rules/apply", { scope: "blank" })
        .then((d) => {
          status.textContent = `Scanned ${d.scanned} · applied ${d.applied} · unmatched ${d.unmatched}`;
          ctx.api.refreshInfiniteCache();
        })
        .catch(() => { status.textContent = "Apply rules failed."; });
    });

    document.getElementById("ml-suggest-btn").addEventListener("click", () => {
      if (!confirm("Store the ML model's top pick as a suggestion on every uncategorized transaction?")) return;
      status.textContent = "Suggesting…";
      ctx.post("/api/ml/suggest-batch", {})
        .then((d) => {
          status.textContent = `Scanned ${d.scanned} · suggested ${d.suggested} · no suggestion ${d.no_suggestion}`;
          ctx.api.refreshInfiniteCache();
        })
        .catch(() => { status.textContent = "ML suggest failed."; });
    });

  }

  makeGrid({
    base: "/api/transactions",
    columnDefs,
    addFields: ["Date", "Description", "Category", "Amount", "Account", "Institution"],
    focusField: "Description",
    deleteNoun: "transaction",
    detailTitle: "Transaction",
    cellHandlers: { Category: onCategoryChanged },
    // A failed save reverts the cell (grid-factory) and says so here; a good one clears it.
    onSaved: (ok, e, d) => {
      const st = saveStatus();
      if (!st) return;
      const field = e.colDef.field || e.colDef.colId;
      st.textContent = ok ? "" : `Could not save ${field}: ${(d && d.error) || "failed"}`;
    },
    onReady: (ctx) => { wireSuggestPanel(ctx); wireToolbar(ctx); },
  });
})();
