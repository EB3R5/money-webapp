// Categories — master-detail CRUD over the lookup tables (categories, accountCategories),
// driven by the context registry the server renders into window.CATEGORIES.contexts. A button
// per context; the left pane lists the sections (Groups) you flip through, the right pane is
// an editable AG Grid of that section's items. Every edit hits /api/categories/{ctx}/* and the
// server cascades the change onto the target collection (transactions / balanceHistory),
// reporting how many rows it touched.
(function () {
  const CONTEXTS = window.CATEGORIES.contexts;
  const byField = (slug) => CONTEXTS.find((c) => c.slug === slug);

  let ctx = CONTEXTS[0];        // current context object
  let section = null;           // current section value
  let options = {};             // {field: [distinct values]} for the datalist editors
  let api = null;               // AG Grid api

  const $ = (sel) => document.querySelector(sel);
  const status = (txt) => { $("#categories-status").textContent = txt || ""; };

  const post = (url, body) =>
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                 body: JSON.stringify(body) }).then((r) => r.json());
  const getJSON = (url) => fetch(url).then((r) => r.json());

  // --- a datalist-backed cell editor: pick an existing value or type a new one --------
  function DatalistEditor() {}
  DatalistEditor.prototype.init = function (params) {
    this.field = params.colDef.field;
    this.input = document.createElement("input");
    this.input.className = "cat-editor";
    this.input.value = params.value == null ? "" : params.value;
    const listId = "dl-" + this.field.replace(/\W/g, "_");
    let dl = document.getElementById(listId);
    if (!dl) { dl = document.createElement("datalist"); dl.id = listId; document.body.appendChild(dl); }
    dl.innerHTML = "";
    (options[this.field] || []).forEach((v) => {
      const o = document.createElement("option"); o.value = v; dl.appendChild(o);
    });
    this.input.setAttribute("list", listId);
  };
  DatalistEditor.prototype.getGui = function () { return this.input; };
  DatalistEditor.prototype.afterGuiAttached = function () { this.input.focus(); this.input.select(); };
  DatalistEditor.prototype.getValue = function () { return this.input.value.trim(); };

  // --- grid -------------------------------------------------------------------------
  function columnDefs() {
    const defs = [{ headerName: "", checkboxSelection: true, headerCheckboxSelection: true,
                    width: 44, pinned: "left", sortable: false, resizable: false, editable: false }];
    ctx.columns.forEach((col) => {
      defs.push({
        field: col, editable: true, flex: 1, minWidth: 130, cellClass: "editable-cell",
        cellEditor: col === ctx.item_field ? "agTextCellEditor" : DatalistEditor,
      });
    });
    return defs;
  }

  function buildGrid() {
    if (api) { api.destroy(); }
    api = agGrid.createGrid($("#grid"), {
      columnDefs: columnDefs(),
      rowData: [],
      defaultColDef: { sortable: true, resizable: true },
      rowSelection: "multiple",
      suppressRowClickSelection: true,
      getRowId: (p) => p.data._id,
      onCellValueChanged: onEdit,
    });
  }

  function onEdit(e) {
    const field = e.colDef.field;
    status("Saving…");
    post(`/api/categories/${ctx.slug}/update`, { id: e.data._id, field, value: e.newValue })
      .then((d) => {
        if (!d.ok) { e.node.setDataValue(field, e.oldValue); status("⚠ " + (d.error || "failed")); return; }
        const n = d.updated || 0;
        status(`✓ updated ${n} ${ctx.target_noun}${n === 1 ? "" : "s"}`);
        // Moving an item to another Group removes it from this section's view.
        if (field === ctx.section_field) { loadSections(); loadItems(section); }
      })
      .catch(() => { e.node.setDataValue(field, e.oldValue); status("⚠ network error"); });
  }

  // --- data loads -------------------------------------------------------------------
  function loadSections(keep) {
    return getJSON(`/api/categories/${ctx.slug}/sections`).then((d) => {
      options = d.options || {};
      const list = $("#section-list");
      list.innerHTML = "";
      (d.sections || []).forEach((s) => {
        const li = document.createElement("li");
        li.textContent = s;
        li.className = "section-item" + (s === section ? " active" : "");
        li.addEventListener("click", () => selectSection(s));
        list.appendChild(li);
      });
      if (!keep) {
        const next = (d.sections || []).includes(section) ? section : (d.sections || [])[0] || null;
        selectSection(next);
      }
    });
  }

  function selectSection(s) {
    section = s;
    document.querySelectorAll("#section-list .section-item").forEach((li) => {
      li.classList.toggle("active", li.textContent === s);
    });
    $("#detail-title").textContent = s ? `${ctx.section_field}: ${s}` : "—";
    if (s) loadItems(s); else if (api) api.setGridOption("rowData", []);
  }

  function loadItems(s) {
    return getJSON(`/api/categories/${ctx.slug}?section=${encodeURIComponent(s)}`)
      .then((d) => { if (api) api.setGridOption("rowData", d.items || []); });
  }

  // --- context switch ---------------------------------------------------------------
  function selectContext(slug) {
    ctx = byField(slug);
    section = null;
    document.querySelectorAll(".ctx-tab").forEach((b) => b.classList.toggle("active", b.dataset.slug === slug));
    $("#section-label").textContent = ctx.section_field;
    buildGrid();
    loadSections();
  }

  // --- add row ----------------------------------------------------------------------
  const modal = $("#row-modal");
  const form = $("#row-form");

  function openAdd() {
    $("#row-modal-title").textContent = `Add ${ctx.item_noun}`;
    const wrap = $("#row-fields");
    wrap.innerHTML = "";
    ctx.columns.forEach((col) => {
      const id = "f-" + col.replace(/\W/g, "_");
      const label = document.createElement("label");
      label.className = "field";
      const span = document.createElement("span"); span.textContent = col;
      const input = document.createElement("input");
      input.type = "text"; input.name = col; input.id = id;
      if (col === ctx.section_field && section) input.value = section;
      if (col !== ctx.item_field && options[col]) {
        const listId = "addl-" + col.replace(/\W/g, "_");
        let dl = document.getElementById(listId);
        if (!dl) { dl = document.createElement("datalist"); dl.id = listId; document.body.appendChild(dl); }
        dl.innerHTML = "";
        options[col].forEach((v) => { const o = document.createElement("option"); o.value = v; dl.appendChild(o); });
        input.setAttribute("list", listId);
      }
      label.appendChild(span); label.appendChild(input);
      wrap.appendChild(label);
    });
    $("#row-status").textContent = "";
    modal.hidden = false;
    const first = form.elements[ctx.item_field];
    if (first) first.focus();
  }
  const closeAdd = () => { modal.hidden = true; };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const payload = {};
    ctx.columns.forEach((col) => {
      const v = (form.elements[col].value || "").trim();
      if (v !== "") payload[col] = v;
    });
    $("#row-status").textContent = "Adding…";
    post(`/api/categories/${ctx.slug}/row`, payload).then((d) => {
      if (!d.ok) { $("#row-status").textContent = "Error: " + (d.error || "failed"); return; }
      closeAdd();
      const added = payload[ctx.section_field];
      loadSections(true).then(() => selectSection(added || section));
    }).catch(() => { $("#row-status").textContent = "Network error"; });
  });

  // --- delete -----------------------------------------------------------------------
  function deleteRow(row, reassign) {
    const body = { id: row._id };
    if (reassign) body.reassign_to = reassign;
    return post(`/api/categories/${ctx.slug}/delete`, body).then((d) => {
      if (d.ok) return true;
      if (d.in_use) {
        const dest = window.prompt(
          `"${row[ctx.item_field]}" is in use by ${d.in_use} ${ctx.target_noun}(s).\n` +
          `Type another ${ctx.item_noun} to reassign them to, or Cancel.`);
        if (dest) return deleteRow(row, dest.trim());
        return false;
      }
      status("⚠ " + (d.error || "delete failed"));
      return false;
    });
  }

  function deleteSelected() {
    const rows = api.getSelectedRows();
    if (!rows.length) { alert("Select one or more rows first."); return; }
    if (!confirm(`Delete ${rows.length} ${ctx.item_noun}(s)? Logged, not undoable in the UI.`)) return;
    (async () => {
      let n = 0;
      for (const r of rows) { if (await deleteRow(r)) n++; }
      status(`✓ deleted ${n}`);
      loadSections(true).then(() => loadItems(section));
    })();
  }

  // --- wiring -----------------------------------------------------------------------
  document.querySelectorAll(".ctx-tab").forEach((b) =>
    b.addEventListener("click", () => selectContext(b.dataset.slug)));
  $("#add-row").addEventListener("click", openAdd);
  $("#row-close").addEventListener("click", closeAdd);
  $("#row-cancel").addEventListener("click", closeAdd);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeAdd(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeAdd(); });
  $("#delete-rows").addEventListener("click", deleteSelected);
  $("#add-section").addEventListener("click", () => {
    const name = window.prompt(`New ${ctx.section_field}? (becomes a section once you add an ${ctx.item_noun})`);
    if (name && name.trim()) { section = name.trim(); selectSection(section); openAdd(); }
  });

  selectContext(ctx.slug);
})();
