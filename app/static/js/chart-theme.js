// The charts' share of the columnar pad: the app's type and ink for every ECharts instance.
// Loaded right after echarts.min.js; the theme becomes the default so no chart script changes.
(function () {
  if (!window.echarts) return;
  const ink = "#1b2430", graphite = "#5c6670", rule = "#dde2d8";
  const font = '"Atkinson Hyperlegible", system-ui, sans-serif';
  echarts.registerTheme("pad", {
    color: ["#4f6b8c", "#2f6b4f", "#a4302a", "#8a6414", "#5b3fa6", "#5c6670"],
    backgroundColor: "transparent",
    textStyle: { fontFamily: font, color: ink },
    title: { textStyle: { fontFamily: font, color: ink, fontWeight: 600 } },
    legend: { textStyle: { fontFamily: font, color: ink } },
    tooltip: { backgroundColor: "#f9faf6", borderColor: "#c3cbbf", textStyle: { fontFamily: font, color: ink } },
    categoryAxis: { axisLine: { lineStyle: { color: "#c3cbbf" } }, axisTick: { show: false },
      axisLabel: { color: graphite, fontFamily: font }, splitLine: { lineStyle: { color: rule } } },
    valueAxis: { axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: graphite, fontFamily: font }, splitLine: { lineStyle: { color: rule } } },
  });
  const init = echarts.init;
  echarts.init = function (el, theme, opts) { return init.call(echarts, el, theme || "pad", opts); };
})();
