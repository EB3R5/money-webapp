// Balances grid — config for makeGrid (app/static/js/grid-factory.js).
// Inline edit / add row / delete selected over the balanceHistory collection.
(function () {
  const columnDefs = [
    { field: "Date", width: 130, sort: "desc", editable: true, cellClass: "editable-cell",
      checkboxSelection: true },
    { field: "Account", flex: 2, minWidth: 200, editable: true, cellClass: "editable-cell" },
    { field: "Institution", flex: 1, minWidth: 140, editable: true, cellClass: "editable-cell" },
    { field: "Class", width: 130, editable: true, cellClass: "editable-cell" },
    { field: "Account Type", width: 150, editable: true, cellClass: "editable-cell" },
    { field: "Balance", width: 150, type: "rightAligned", valueFormatter: window.gridMoney,
      editable: true, cellClass: "editable-cell money-col", headerClass: "money-col",
      valueParser: (p) => p.newValue === "" ? null : Number(String(p.newValue).replace(/[$,]/g, "")),
      cellClassRules: { "neg": (p) => p.value < 0, "pos": (p) => p.value > 0 } },
  ];

  makeGrid({
    base: "/api/balances",
    columnDefs,
    addFields: ["Date", "Account", "Institution", "Class", "Account Type", "Balance"],
    focusField: "Account",
    deleteNoun: "balance row",
    detailTitle: "Balance snapshot",
  });
})();
