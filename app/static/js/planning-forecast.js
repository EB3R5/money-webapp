// Planner — the checking forecast card: fetches /api/planning/forecast and draws the daily
// balance (ECharts) with event markers and the low point, the callout line, and the events
// table. Everything shown is an estimate from the ledger; the card says so in its title.
(function () {
  const C = (role) => window.chartTheme.color(role);   // the user's chart colours (chart-theme.js)
  const usd = (v) => (v < 0 ? "−" : "") + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
  const signed = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const day = (iso) => { const d = new Date(iso + "T12:00:00"); return d.getDate() + " " + MON[d.getMonth()]; };
  const el = document.getElementById("chart-forecast");
  const callout = document.getElementById("forecast-callout");
  const table = document.getElementById("forecast-events");
  if (!el || typeof echarts === "undefined") return;
  const chart = echarts.init(el);

  fetch("/api/planning/forecast")
    .then((r) => r.json())
    .then((f) => {
      if (f.error) { callout.innerHTML = '<span class="neg">' + f.error + "</span>"; return; }
      const lowBad = f.low.balance < 0;
      callout.innerHTML =
        "<span>Now <b>" + usd(f.start_balance) + "</b></span>" +
        "<span>Lowest <b class=\"" + (lowBad ? "neg" : "") + "\">" + usd(f.low.balance) + "</b> on " + day(f.low.date) + "</span>" +
        "<span>In " + f.days + " days <b>" + usd(f.end_balance) + "</b></span>" +
        "<span class=\"muted\">" + (f.accounts.length ? f.accounts.join(" + ") : "no checking account found") +
        " · assumes " + usd(f.daily_variable) + "/day variable spend</span>";

      const byDate = {};
      f.events.forEach((e) => { (byDate[e.date] = byDate[e.date] || []).push(e); });
      const marks = Object.keys(byDate).map((d) => {
        const evs = byDate[d]; const last = evs[evs.length - 1];
        const income = evs.some((e) => e.amount > 0);
        return { coord: [d, last.balance_after], itemStyle: { color: income ? C("net") : C("spend") }, symbol: "circle", symbolSize: 8,
                 value: evs.map((e) => e.label + " " + signed(e.amount)).join(", ") };
      });
      chart.setOption({
        tooltip: { trigger: "axis", formatter: (ps) => { const p = ps[0]; const evs = byDate[p.axisValue] || [];
          return day(p.axisValue) + "<br>" + usd(p.value) + (evs.length ? "<br>" + evs.map((e) => e.label + " " + signed(e.amount)).join("<br>") : ""); } },
        grid: { left: 64, right: 16, top: 16, bottom: 28 },
        xAxis: { type: "category", data: f.series.map((p) => p.date), axisLabel: { formatter: (v) => (v.slice(8) === "01" ? MON[+v.slice(5, 7) - 1] : "") , interval: 0 }, axisTick: { show: false } },
        yAxis: { type: "value", axisLabel: { formatter: usd }, splitLine: { lineStyle: { color: "rgba(0,0,0,.08)" } } },
        series: [{
          type: "line", data: f.series.map((p) => p.balance), showSymbol: false, lineStyle: { width: 2, color: C("net") },
          areaStyle: { color: "rgba(79,107,140,.08)" },
          markPoint: { data: marks.concat([{ coord: [f.low.date, f.low.balance], symbol: "pin", symbolSize: 34, itemStyle: { color: C("spend") },
            label: { formatter: "low", color: "#fff", fontSize: 10 }, value: "low " + usd(f.low.balance) }]), label: { show: false } },
          markLine: { silent: true, symbol: "none", lineStyle: { color: "rgba(0,0,0,.25)", type: "dashed" }, data: [{ yAxis: 0 }], label: { show: false } },
        }],
      });

      table.innerHTML = "<thead><tr><th>Date</th><th>Event</th><th class=\"r\">Amount</th><th class=\"r\">Balance after</th></tr></thead><tbody>" +
        (f.events.length ? f.events.map((e) =>
          "<tr><td class=\"muted\">" + day(e.date) + "</td><td>" + e.label + "</td><td class=\"r " + (e.amount > 0 ? "pos" : "") + "\">" + signed(e.amount) +
          "</td><td class=\"r " + (e.balance_after < 0 ? "neg" : "") + "\">" + usd(e.balance_after) + "</td></tr>").join("")
          : "<tr><td class=\"muted\" colspan=\"4\">No recurring income or bills found in the last two years; the line is the variable spend only.</td></tr>") +
        "</tbody>";
    })
    .catch(() => { callout.innerHTML = '<span class="neg">Could not load the forecast.</span>'; });

  window.addEventListener("resize", () => chart.resize());
})();
