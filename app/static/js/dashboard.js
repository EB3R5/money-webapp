// Dashboard — ECharts views fed by /api/dashboard/* aggregation endpoints.
(function () {
  const usd = (v) => "$" + Math.round(v).toLocaleString("en-US");

  const monthly = echarts.init(document.getElementById("chart-monthly"));
  const category = echarts.init(document.getElementById("chart-category"));

  fetch("/api/dashboard/monthly")
    .then((r) => r.json())
    .then((d) => {
      monthly.setOption({
        tooltip: { trigger: "axis", valueFormatter: usd },
        legend: { data: ["Income", "Spend", "Net"], bottom: 0 },
        grid: { left: 60, right: 20, top: 20, bottom: 50 },
        xAxis: { type: "category", data: d.labels },
        yAxis: { type: "value", axisLabel: { formatter: usd } },
        series: [
          { name: "Income", type: "bar", stack: "flow", data: d.income, itemStyle: { color: "#2f6b4f" } },
          { name: "Spend", type: "bar", stack: "flow", data: d.spend.map((v) => -v), itemStyle: { color: "#a4302a" } },
          { name: "Net", type: "line", data: d.net, smooth: true, itemStyle: { color: "#4f6b8c" } },
        ],
      });
    });

  fetch("/api/dashboard/by-category")
    .then((r) => r.json())
    .then((d) => {
      category.setOption({
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: usd },
        grid: { left: 140, right: 30, top: 20, bottom: 30 },
        xAxis: { type: "value", axisLabel: { formatter: usd } },
        yAxis: { type: "category", data: d.categories.slice().reverse(), axisLabel: { width: 130, overflow: "truncate" } },
        series: [{ type: "bar", data: d.spend.slice().reverse(), itemStyle: { color: "#4f6b8c" } }],
      });
    });

  window.addEventListener("resize", () => { monthly.resize(); category.resize(); });
})();
