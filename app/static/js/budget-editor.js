// Budget editor — a client-side AG Grid over one version's embedded lines (a few dozen
// groups, all loaded at once, unlike the infinite ledger grid). Inline-edit Amount,
// add/delete group rows, and a live total. Every edit persists immediately;
// "Save version" just flips the status pill.
(function () {
  const id = window.BUDGET.id;
  const base = "/budgets/api/" + encodeURIComponent(id);
  const post = (url, body) =>
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                 body: JSON.stringify(body || {}) }).then((r) => r.json());

  const money = (p) => p.value == null ? "" :
    Number(p.value).toLocaleString("en-US", { style: "currency", currency: "USD" });

  const totalEl = document.getElementById("budget-total");
  function refreshTotal() {
    let sum = 0;
    api.forEachNode((n) => { sum += Number(n.data.amount) || 0; });
    totalEl.textContent = sum.toLocaleString("en-US", { style: "currency", currency: "USD" });
  }

  const columnDefs = [
    { headerName: "", width: 44, checkboxSelection: true, headerCheckboxSelection: true,
      sortable: false, resizable: false, pinned: "left" },
    { field: "group", headerName: "Group", flex: 1, minWidth: 200, sort: "asc" },
    { field: "amount", headerName: "Amount", width: 160, type: "rightAligned",
      editable: true, cellClass: "editable-cell", valueFormatter: money,
      valueParser: (p) => p.newValue === "" ? 0 : Number(String(p.newValue).replace(/[$,]/g, "")),
      cellClassRules: { neg: (p) => p.value < 0, pos: (p) => p.value > 0 } },
    { field: "source", headerName: "Source", width: 130,
      cellClass: (p) => p.value === "historical" ? "muted" : "" },
    { field: "dataPoints", headerName: "Months", width: 110, type: "rightAligned" },
  ];

  const gridOptions = {
    columnDefs,
    rowData: window.BUDGET.lines || [],
    defaultColDef: { sortable: true, resizable: true },
    rowSelection: "multiple",
    getRowId: (p) => p.data.group,
    onCellValueChanged: (e) => {
      if (e.colDef.field !== "amount") return;
      post(base + "/line/update", { group: e.data.group, amount: e.newValue })
        .then((d) => {
          if (!d.ok) { e.node.setDataValue("amount", e.oldValue); return; }
          e.node.setDataValue("source", "manual");
          refreshTotal();
        })
        .catch(() => e.node.setDataValue("amount", e.oldValue));
    },
  };

  const api = agGrid.createGrid(document.querySelector("#grid"), gridOptions);
  refreshTotal();

  // Add group.
  const modal = document.getElementById("add-modal");
  const form = document.getElementById("add-form");
  const addStatus = document.getElementById("add-status");
  const openAdd = () => { form.reset(); form.elements["amount"].value = "0"; addStatus.textContent = "";
                          modal.hidden = false; form.elements["group"].focus(); };
  const closeAdd = () => { modal.hidden = true; };

  document.getElementById("add-line").addEventListener("click", openAdd);
  document.getElementById("add-close").addEventListener("click", closeAdd);
  document.getElementById("add-cancel").addEventListener("click", closeAdd);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeAdd(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeAdd(); });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const group = form.elements["group"].value.trim();
    if (!group) return;
    addStatus.textContent = "Adding…";
    post(base + "/line/add", { group, amount: form.elements["amount"].value })
      .then((d) => {
        if (!d.ok) { addStatus.textContent = "Error: " + (d.error || "failed"); return; }
        api.applyTransaction({ add: [d.line] });
        refreshTotal();
        closeAdd();
      })
      .catch(() => { addStatus.textContent = "Network error"; });
  });

  // Delete selected.
  document.getElementById("delete-lines").addEventListener("click", () => {
    const rows = api.getSelectedRows();
    if (!rows.length) { alert("Select one or more rows first."); return; }
    const groups = rows.map((r) => r.group);
    if (!confirm(`Remove ${groups.length} group(s) from this budget?`)) return;
    post(base + "/line/delete", { groups }).then((d) => {
      if (d.ok) { api.applyTransaction({ remove: rows }); refreshTotal(); }
    });
  });

  // Save version → flip the pill.
  document.getElementById("save-budget").addEventListener("click", () => {
    post(base + "/save").then((d) => {
      if (d.ok) {
        const pill = document.getElementById("status-pill");
        pill.textContent = "saved";
        pill.className = "pill pill-saved";
      }
    });
  });
})();
