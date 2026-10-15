// Planner page — bar widths from data attributes (the CSP allows no style attributes in
// markup) and the journal drawer's open/close; planning-entry.js owns the entry itself.
(function () {
  document.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w + "%"; });
  const drawer = document.getElementById("drawer");
  document.getElementById("drawer-open").addEventListener("click", () => {
    drawer.classList.add("open");
    const ta = document.getElementById("entry-body");
    if (ta) ta.focus();
  });
  document.getElementById("drawer-close").addEventListener("click", () => drawer.classList.remove("open"));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") drawer.classList.remove("open"); });
})();
