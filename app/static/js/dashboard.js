// Dashboard — ECharts views fed by /api/dashboard/* aggregation endpoints. The series colours
// come from chartTheme (the user's chart colours); the panel's preview fires "chart-colours"
// and both charts are drawn again from the data already fetched.
(function () {
  const usd = (v) => "$" + Math.round(v).toLocaleString("en-US");
  const color = (role) => window.chartTheme.color(role);

  let monthly = echarts.init(document.getElementById("chart-monthly"));
  let category = echarts.init(document.getElementById("chart-category"));
  let monthlyData = null, categoryData = null;

  const drawMonthly = (d) => monthly.setOption({
    tooltip: { trigger: "axis", valueFormatter: usd },
    legend: { data: ["Income", "Spend", "Net"], bottom: 0 },
    grid: { left: 60, right: 20, top: 20, bottom: 50 },
    xAxis: { type: "category", data: d.labels },
    yAxis: { type: "value", axisLabel: { formatter: usd } },
    series: [
      { name: "Income", type: "bar", stack: "flow", data: d.income, itemStyle: { color: color("income") } },
      { name: "Spend", type: "bar", stack: "flow", data: d.spend.map((v) => -v), itemStyle: { color: color("spend") } },
      { name: "Net", type: "line", data: d.net, smooth: true, itemStyle: { color: color("net") } },
    ],
  });
  const drawCategory = (d) => category.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: usd },
    grid: { left: 140, right: 30, top: 20, bottom: 30 },
    xAxis: { type: "value", axisLabel: { formatter: usd } },
    yAxis: { type: "category", data: d.categories.slice().reverse(), axisLabel: { width: 130, overflow: "truncate" } },
    series: [{ type: "bar", data: d.spend.slice().reverse(), itemStyle: { color: color("net") } }],
  });

  fetch("/api/dashboard/monthly").then((r) => r.json()).then((d) => { monthlyData = d; drawMonthly(d); });
  fetch("/api/dashboard/by-category").then((r) => r.json()).then((d) => { categoryData = d; drawCategory(d); });

  document.addEventListener("chart-colours", () => {
    // chartTheme.refresh() replaces the instances next; these two are drawn fresh here instead.
    monthly.dispose(); category.dispose();
    monthly = echarts.init(document.getElementById("chart-monthly"));
    category = echarts.init(document.getElementById("chart-category"));
    if (monthlyData) drawMonthly(monthlyData);
    if (categoryData) drawCategory(categoryData);
  });
  window.addEventListener("resize", () => { monthly.resize(); category.resize(); });
})();
