// Financial Health — save/delete a period, then reload to recompute the ratios server-side.
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

  const form = document.getElementById("health-form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {};
      new FormData(form).forEach((v, k) => { body[k] = v; });
      try {
        const d = await postJSON("/api/health-analysis/save", body);
        location.href = "/health-analysis?period=" + encodeURIComponent(d.id);
      } catch (err) {
        alert("Could not save: " + err.message);
      }
    });
  }

  const del = document.getElementById("delete-period");
  if (del) {
    del.addEventListener("click", async () => {
      if (!confirm("Delete this period?")) return;
      try {
        await postJSON("/api/health-analysis/delete", { id: del.dataset.id });
        location.href = "/health-analysis";
      } catch (err) {
        alert("Could not delete: " + err.message);
      }
    });
  }
})();
