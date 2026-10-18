// The charts' share of the columnar pad: the app's type and ink for every ECharts instance,
// and the six series colours, read from the --chart-* tokens on <html> (app.css defaults,
// the user's own from base.html). Loaded right after echarts.min.js; the theme becomes the
// default so no chart script names it.
//   chartTheme.color("income")  — a role's current colour, for a series' explicit itemStyle
//   chartTheme.refresh()        — re-read the tokens, re-register the theme and redraw every
//                                 chart made through echarts.init (the colours panel's preview)
(function () {
  if (!window.echarts) return;
  const ROLES = ["net", "income", "spend", "s4", "s5", "s6"];
  const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const color = (role) => token("--chart-" + role);
  const font = '"Atkinson Hyperlegible", system-ui, sans-serif';
  const theme = () => {
    const ink = token("--ink") || "#1b2430", graphite = token("--graphite") || "#5c6670";
    const rule = token("--rule") || "#c3cbbf", soft = token("--rule-soft") || "#dde2d8";
    return {
      color: ROLES.map(color),
      backgroundColor: "transparent",
      textStyle: { fontFamily: font, color: ink },
      title: { textStyle: { fontFamily: font, color: ink, fontWeight: 600 } },
      legend: { textStyle: { fontFamily: font, color: ink } },
      tooltip: { backgroundColor: token("--sheet") || "#f9faf6", borderColor: rule, textStyle: { fontFamily: font, color: ink } },
      categoryAxis: { axisLine: { lineStyle: { color: rule } }, axisTick: { show: false },
        axisLabel: { color: graphite, fontFamily: font }, splitLine: { lineStyle: { color: soft } } },
      valueAxis: { axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: graphite, fontFamily: font }, splitLine: { lineStyle: { color: soft } } },
    };
  };
  echarts.registerTheme("pad", theme());

  // Every chart on the page, with the option it was last given, so refresh() can redraw it.
  const charts = [];
  const init = echarts.init;
  echarts.init = function (el, name, opts) {
    const inst = init.call(echarts, el, name || "pad", opts);
    const rec = { el, name, opts, inst, option: null };
    charts.push(rec);
    const setOption = inst.setOption;
    inst.setOption = function (option, ...rest) { rec.option = option; return setOption.call(inst, option, ...rest); };
    return inst;
  };
  const refresh = () => {
    echarts.registerTheme("pad", theme());
    const pending = charts.splice(0);
    document.dispatchEvent(new CustomEvent("chart-colours"));     // pages that build colours into their options redraw their own
    for (const rec of pending) {
      if (!rec.option || !document.contains(rec.el) || rec.inst.isDisposed()) continue;
      rec.inst.dispose();
      echarts.init(rec.el, rec.name, rec.opts).setOption(rec.option);
    }
  };
  window.chartTheme = { color, refresh };
})();
