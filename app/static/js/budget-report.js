// Budget-vs-Actual report grid — read-only AG Grid that ports Budget v2's
// conditional formatting (budget-vs-actual.js applyConditionalFormatting) to cellStyle:
//   Variance      → solid green (favorable, >0) / red (unfavorable, <0)
//   Variance_Pct  → gradient red(-25%) → white(0) → green(+25%)
//   Score         → gradient red(0) → yellow(50) → green(100)
//   Alert_Level   → the seven discrete v2 label colors, plus grey "Unbudgeted"
// Rows are the union of budget lines and groups with activity; `match` says which side
// a row came from, and actual-only rows have no pct/score (nothing to score against).
(function () {
  const money = (p) => p.value == null ? "" :
    Number(p.value).toLocaleString("en-US", { style: "currency", currency: "USD" });
  const pct = (p) => p.value == null ? "" :
    (Number(p.value) * 100).toFixed(2) + "%";

  // --- color helpers: piecewise-linear interpolation between hex stops --------
  const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  const rgb = (a) => `rgb(${a.map((n) => Math.round(n)).join(",")})`;
  const lerp = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);

  // stops: [[value, "#hex"], ...] ascending; clamps outside the range.
  function gradient(value, stops) {
    if (value <= stops[0][0]) return rgb(hex(stops[0][1]));
    const last = stops[stops.length - 1];
    if (value >= last[0]) return rgb(hex(last[1]));
    for (let i = 1; i < stops.length; i++) {
      if (value <= stops[i][0]) {
        const [v0, c0] = stops[i - 1], [v1, c1] = stops[i];
        return rgb(lerp(hex(c0), hex(c1), (value - v0) / (v1 - v0)));
      }
    }
    return "#ffffff";
  }

  const PCT_STOPS = [[-0.25, "#ea4335"], [0, "#ffffff"], [0.25, "#34a853"]];
  const SCORE_STOPS = [[0, "#ea4335"], [50, "#fbbc04"], [100, "#34a853"]];

  // Alert colors keyed by SEVERITY × FAVOURABILITY, not the Under/Over word — because
  // for income "Over" (earning more than target) is favourable while for an expense it
  // isn't. row.favorable carries the kind-aware verdict from the server.
  const FAV =   { Critical: { bg: "#2f6b4f", fg: "#fff" }, High: { bg: "#34a853", fg: "#fff" },
                  Medium: { bg: "#d9ead3", fg: "#274e13" } };
  const UNFAV = { Critical: { bg: "#ea4335", fg: "#fff" }, High: { bg: "#ff6d01", fg: "#fff" },
                  Medium: { bg: "#e6b8af", fg: "#85200c" } };
  const MATCH_LABEL = { both: "✓", budget_only: "Budget only", actual_only: "Actual only" };
  function alertStyle(row) {
    if (!row) return null;
    if (row.alert_level === "Unbudgeted")
      return { backgroundColor: "#dde2d8", color: "#1b2430", fontWeight: 600 };
    if (row.alert_level === "On Target")
      return { backgroundColor: "#e4eaf0", color: "#4f6b8c", fontWeight: 600 };
    const sev = row.alert_level.split(" ")[0];
    const c = (row.favorable ? FAV : UNFAV)[sev];
    return c ? { backgroundColor: c.bg, color: c.fg, fontWeight: 600 } : null;
  }
  // Variance solid fill by favourability (kind-aware), replacing v2's raw-sign rule.
  const favFill = (fav) => fav ? { backgroundColor: "#d9ead3", color: "#274e13" }
                               : { backgroundColor: "#f3e3e0", color: "#a61c00" };

  const columnDefs = [
    { field: "group", headerName: "Group", flex: 1, minWidth: 170, sort: null },
    { field: "match", headerName: "Match", width: 120,
      valueFormatter: (p) => MATCH_LABEL[p.value] || "",
      cellStyle: (p) => p.value === "both" ? { color: "#2f6b4f" } : { color: "#5c6670", fontStyle: "italic" } },
    { field: "kind", headerName: "Type", width: 100,
      cellStyle: (p) => p.value === "income" ? { color: "#2f6b4f", fontWeight: 600 } : { color: "#5c6670" } },
    // No default column sort: the server orders rows by budget asc with actual-only rows
    // last, which a plain sort on Budget (0 for actual-only) would put first.
    { field: "budget_amount", headerName: "Budget", width: 130, type: "rightAligned",
      valueFormatter: money },
    { field: "actual_amount", headerName: "Actual", width: 130, type: "rightAligned",
      valueFormatter: money },
    { field: "variance", headerName: "Variance", width: 130, type: "rightAligned",
      valueFormatter: money,
      cellStyle: (p) => p.value === 0 ? null : favFill(p.data.favorable) },
    { field: "variance_pct", headerName: "Variance %", width: 120, type: "rightAligned",
      valueFormatter: pct,
      cellStyle: (p) => p.value == null ? null : ({ backgroundColor: gradient(Number(p.value), PCT_STOPS) }) },
    { field: "score", headerName: "Score", width: 100, type: "rightAligned",
      cellStyle: (p) => p.value == null ? null : ({ backgroundColor: gradient(Number(p.value), SCORE_STOPS),
                                                   color: Number(p.value) < 50 ? "#fff" : "#1b2430" }) },
    { field: "alert_level", headerName: "Alert", width: 150,
      cellStyle: (p) => alertStyle(p.data) },
  ];

  agGrid.createGrid(document.querySelector("#grid"), {
    columnDefs,
    rowData: window.REPORT.rows || [],
    defaultColDef: { sortable: true, resizable: true },
    getRowId: (p) => p.data.group,      // still unique: the union is de-duplicated by group
  });
})();
