// Metrics — Savings section: ECharts savings-vs-target chart + category-mapping / goal /
// config CRUD. Mutations POST JSON to /api/metrics/savings/* then reload to repaint the
// server-rendered tables.
(function () {
  const C = (role) => window.chartTheme.color(role);   // the user's chart colours (chart-theme.js)
  const usd = (v) => "$" + Math.round(v).toLocaleString("en-US");
  const pct = (v) => (v * 100).toFixed(1) + "%";
  const year = window.METRICS_YEAR;

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || "request failed");
    return data;
  }

  // --- chart ---------------------------------------------------------------
  const el = document.getElementById("chart-savings");
  const chart = el ? echarts.init(el) : null;
  if (chart) {
    fetch("/api/metrics/savings?year=" + year)
      .then((r) => r.json())
      .then((d) => {
        const rows = d.rows || [];
        chart.setOption({
          tooltip: { trigger: "axis" },
          legend: { data: ["Saved", "Target", "Rate"], bottom: 0 },
          grid: { left: 60, right: 60, top: 20, bottom: 50 },
          xAxis: { type: "category", data: rows.map((r) => r.month) },
          yAxis: [
            { type: "value", name: "$", axisLabel: { formatter: usd } },
            { type: "value", name: "rate", max: 1, axisLabel: { formatter: (v) => pct(v) } },
          ],
          series: [
            { name: "Saved", type: "bar", data: rows.map((r) => r.savings), itemStyle: { color: C("income") } },
            { name: "Target", type: "line", data: rows.map((r) => r.target), itemStyle: { color: C("spend") } },
            { name: "Rate", type: "line", yAxisIndex: 1, smooth: true, data: rows.map((r) => r.rate), itemStyle: { color: C("net") } },
          ],
        });
      });
    window.addEventListener("resize", () => chart.resize());
  }

  // --- projections: actual balance (solid) + forward (dashed) + goal lines --
  const projEl = document.getElementById("chart-projections");
  if (projEl) {
    const pc = echarts.init(projEl);
    fetch("/api/metrics/savings/projections?year=" + year)
      .then((r) => r.json())
      .then((d) => {
        const hist = d.history || [], fwd = d.forward || [];
        const xs = hist.map((h) => h.month).concat(fwd.map((f) => f.month));
        const actual = hist.map((h) => h.balance).concat(fwd.map(() => null));
        const projected = hist.map(() => null);
        if (hist.length) projected[hist.length - 1] = hist[hist.length - 1].balance;
        fwd.forEach((f) => projected.push(f.projected));
        const goalLines = (d.goals || [])
          .filter((g) => g.target_amount > 0)
          .map((g) => ({ yAxis: g.target_amount, name: g.name,
                         label: { formatter: g.name, position: "insideEndTop" } }));
        pc.setOption({
          tooltip: { trigger: "axis", valueFormatter: usd },
          legend: { data: ["Actual balance", "Projected"], bottom: 0 },
          grid: { left: 70, right: 30, top: 20, bottom: 50 },
          xAxis: { type: "category", data: xs },
          yAxis: { type: "value", axisLabel: { formatter: usd } },
          series: [
            { name: "Actual balance", type: "line", data: actual, smooth: true,
              itemStyle: { color: C("income") },
              markLine: { silent: true, symbol: "none",
                          lineStyle: { type: "dotted", color: C("s6") }, data: goalLines } },
            { name: "Projected", type: "line", data: projected, smooth: true,
              lineStyle: { type: "dashed" }, itemStyle: { color: C("net") } },
          ],
        });
      });
    window.addEventListener("resize", () => pc.resize());
  }

  // --- rate scenarios: actual-to-date + one forward line per rate ----------
  const scenEl = document.getElementById("chart-scenarios");
  if (scenEl) {
    const sc = echarts.init(scenEl);
    fetch("/api/metrics/savings/scenarios?year=" + year)
      .then((r) => r.json())
      .then((d) => {
        const hist = d.history || [], months = d.forward_months || [], scen = d.scenarios || [];
        const xs = hist.map((h) => h.month).concat(months);
        const palette = ["net", "income", "spend", "s4", "s5"].map(C);
        const actual = hist.map((h) => h.balance).concat(months.map(() => null));
        const series = [{ name: "Actual to date", type: "line", data: actual, smooth: true,
                          showSymbol: false, itemStyle: { color: C("s6") } }];
        scen.forEach((s, i) => {
          const arr = hist.map(() => null);
          if (hist.length) arr[hist.length - 1] = d.balance_now;
          s.balances.forEach((b) => arr.push(b));
          series.push({ name: s.label, type: "line", data: arr, smooth: true, showSymbol: false,
                        lineStyle: { type: "dashed" }, itemStyle: { color: palette[i % palette.length] } });
        });
        sc.setOption({
          tooltip: { trigger: "axis", valueFormatter: usd },
          legend: { data: ["Actual to date"].concat(scen.map((s) => s.label)), bottom: 0 },
          grid: { left: 70, right: 30, top: 20, bottom: 50 },
          xAxis: { type: "category", data: xs },
          yAxis: { type: "value", axisLabel: { formatter: usd } },
          series: series,
        });
      });
    window.addEventListener("resize", () => sc.resize());
  }

  // Category-mapping editor (sync button + per-row role edits) is the shared mapping-editor.js
  // island, wired by window.MAPPING_EDITOR in metrics.html.

  // --- add goal ------------------------------------------------------------
  const goalForm = document.getElementById("goal-form");
  if (goalForm) {
    const G = (id) => document.getElementById(id);
    function fillGoal(d) {
      G("goal-id").value = d ? d.editGoal : "";
      G("goal-name").value = d ? d.name : ""; G("goal-target").value = d ? d.target : "";
      G("goal-date").value = d ? d.date : ""; G("goal-per").value = d ? d.per : "";
      G("goal-account").value = d ? d.account : ""; G("goal-override").value = d ? d.override : "";
      G("goal-notes").value = d ? d.notes : "";
      G("goal-submit").textContent = d ? "Save changes" : "Add goal";
      G("goal-form-title").textContent = d ? "Editing " + d.name : "";
      G("goal-cancel").hidden = !d;
      if (d) { goalForm.scrollIntoView({ block: "nearest" }); G("goal-name").focus(); }
    }
    document.querySelectorAll("[data-edit-goal]").forEach((b) => b.addEventListener("click", () => fillGoal(b.dataset)));
    G("goal-cancel").addEventListener("click", () => fillGoal(null));
    goalForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(goalForm);
      const body = {
        name: f.get("name"), target_amount: f.get("target_amount"), target_date: f.get("target_date"),
        monthly_contribution: f.get("monthly_contribution"), balance_account: f.get("balance_account"),
        balance_override: f.get("balance_override"), notes: f.get("notes"),
      };
      try {
        if (f.get("id")) await postJSON("/api/metrics/savings/goals/update", { id: f.get("id"), ...body });
        else await postJSON("/api/metrics/savings/goals", body);
        location.reload();
      } catch (err) {
        alert("Could not save goal: " + err.message);
      }
    });
  }

  // --- delete goal ---------------------------------------------------------
  document.querySelectorAll("[data-del-goal]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this goal?")) return;
      try {
        await postJSON("/api/metrics/savings/goals/delete", { id: btn.dataset.delGoal });
        location.reload();
      } catch (err) {
        alert("Could not delete: " + err.message);
      }
    });
  }
  );

  // --- save config ---------------------------------------------------------
  const cfgForm = document.getElementById("savings-config");
  if (cfgForm) {
    cfgForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(cfgForm);
      try {
        await postJSON("/api/metrics/savings/config", {
          target_rate: f.get("target_rate"),
          income_override: f.get("income_override"),
          scenario_rates: splitCats(f.get("scenario_rates")).map(Number).filter((n) => !isNaN(n)),
        });
        location.reload();
      } catch (err) {
        alert("Could not save: " + err.message);
      }
    });
  }
})();
