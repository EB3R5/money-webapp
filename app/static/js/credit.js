// Credit — score history chart + registry / score / activity CRUD. Mutations POST JSON to
// /api/credit/* then reload to repaint the server-rendered tables.
(function () {
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

  function formToObj(form) {
    const o = {};
    new FormData(form).forEach((v, k) => { o[k] = v; });
    return o;
  }

  // Wire a form to an endpoint; reload on success.
  function wireForm(id, url) {
    const form = document.getElementById(id);
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await postJSON(url, formToObj(form));
        location.reload();
      } catch (err) {
        alert("Could not save: " + err.message);
      }
    });
  }

  // Wire all delete buttons matching a data attribute to an endpoint.
  function wireDeletes(attr, url, confirmMsg) {
    document.querySelectorAll("[" + attr + "]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (confirmMsg && !confirm(confirmMsg)) return;
        try {
          await postJSON(url, { id: btn.getAttribute(attr) });
          location.reload();
        } catch (err) {
          alert("Could not delete: " + err.message);
        }
      });
    });
  }

  wireForm("score-form", "/api/credit/scores");
  wireForm("account-form", "/api/credit/accounts");
  wireForm("activity-form", "/api/credit/activity");
  wireForm("credit-config", "/api/credit/config");
  wireDeletes("data-del-score", "/api/credit/scores/delete", "Delete this score entry?");
  wireDeletes("data-del-account", "/api/credit/accounts/delete", "Delete this account?");
  wireDeletes("data-del-activity", "/api/credit/activity/delete", "Delete this activity entry?");

  // --- score history chart (one line per bureau) ---------------------------
  const el = document.getElementById("chart-score");
  const scores = window.CREDIT_SCORES || [];
  if (el && scores.length) {
    const chart = echarts.init(el);
    const dates = [...new Set(scores.map((s) => s.date))].sort();
    const bureaus = [...new Set(scores.map((s) => s.bureau || "—"))];
    const series = bureaus.map((b) => ({
      name: b,
      type: "line",
      connectNulls: true,
      smooth: true,
      data: dates.map((d) => {
        const hit = scores.find((s) => s.date === d && (s.bureau || "—") === b);
        return hit ? hit.score : null;
      }),
    }));
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: bureaus, bottom: 0 },
      grid: { left: 50, right: 20, top: 20, bottom: 40 },
      xAxis: { type: "category", data: dates },
      yAxis: { type: "value", scale: true, min: 300, max: 850 },
      series: series,
    });
    window.addEventListener("resize", () => chart.resize());
  }
})();
