// Data adapter — one makeGrid whose table is swapped from the <select>. Columns come
// from the server per table; only an editable table (autocat) opens cells for editing;
// edits flash into #status. No add/delete chrome.
(function () {
  const statusEl = document.getElementById("status");
  const flash = (msg, ok = true) => {
    statusEl.textContent = msg;
    statusEl.style.color = ok ? "#2f6b4f" : "#a4302a";
    if (ok) setTimeout(() => { if (statusEl.textContent === msg) statusEl.textContent = ""; }, 1500);
  };

  const grid = window.makeGrid({
    base: "",                                   // set per collection by loadCollection
    rowsPath: "/rows",
    columnDefs: [],
    defaultColDef: { sortable: true, resizable: true, minWidth: 110 },
    onSaved: (ok) => (ok ? flash("saved") : flash("save failed", false)),
  });

  function loadCollection(name) {
    const base = "/api/data/" + encodeURIComponent(name);
    grid.setBase(base);
    fetch(base + "/columns")
      .then((r) => r.json())
      .then((d) => {
        const colDefs = d.columns.map((key) => ({
          colId: key,
          headerName: key,
          editable: !!d.editable,
          // valueGetter/Setter by bracket access — avoids AG Grid treating
          // dotted/spaced field names ('Pred:Conf.Category', 'Account #') as paths.
          valueGetter: (p) => (p.data ? p.data[key] : null),
          valueSetter: (p) => { p.data[key] = p.newValue; return true; },
        }));
        grid.setColumns(colDefs, name);
      });
  }

  const select = document.getElementById("table");
  select.addEventListener("change", (e) => {
    grid.setQuery("");
    document.getElementById("search").value = "";
    loadCollection(e.target.value);
  });

  if (select.value) loadCollection(select.value);
})();
