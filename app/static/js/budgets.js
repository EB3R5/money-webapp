// Budgets list page — the "new budget" modal (POST a seeded draft, then open its
// editor) and per-row delete. No grid here; the version table is server-rendered.
(function () {
  const post = (url, body) =>
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                 body: JSON.stringify(body || {}) }).then((r) => r.json());

  const modal = document.getElementById("new-modal");
  const form = document.getElementById("new-form");
  const status = document.getElementById("new-status");

  const open = () => { status.textContent = ""; modal.hidden = false; form.elements["versionName"].focus(); };
  const close = () => { modal.hidden = true; };

  document.getElementById("new-budget").addEventListener("click", open);
  document.getElementById("new-close").addEventListener("click", close);
  document.getElementById("new-cancel").addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) close(); });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    status.textContent = "Seeding from history…";
    post("/budgets/api/new", {
      month: form.elements["month"].value,
      versionName: form.elements["versionName"].value.trim(),
    }).then((d) => {
      if (!d.ok) { status.textContent = "Error: " + (d.error || "failed"); return; }
      window.location.href = "/budgets/" + encodeURIComponent(d.id);
    }).catch(() => { status.textContent = "Network error"; });
  });

  // Per-row delete.
  document.querySelectorAll(".btn-del").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      if (!confirm(`Delete budget "${btn.dataset.name}"? This cannot be undone.`)) return;
      post("/budgets/api/" + encodeURIComponent(id) + "/delete").then((d) => {
        if (d.ok) btn.closest("tr").remove();
      });
    });
  });
})();
