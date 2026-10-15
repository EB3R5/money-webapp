// Page-wide behaviours that used to be inline handlers. The CSP allows no inline
// event attributes (script-src is nonce-only), so an onchange/onclick in a template
// silently never runs. Loaded by base.html on every page, after csrf.js.
//   form.year-picker > select   — change submits the form (the report / period pickers)
//   [data-print]                — click prints the page
//   .report-scroll table        — the second label column sticks beside the first (--lbl1)
(function () {
  document.addEventListener("change", (e) => {
    const sel = e.target;
    if (!(sel instanceof HTMLSelectElement)) return;
    const form = sel.closest("form.year-picker");
    if (!form) return;
    if (typeof form.requestSubmit === "function") form.requestSubmit(); else form.submit();
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest && e.target.closest("[data-print]")) window.print();
  });

  // A report scrolls sideways inside its frame; its first two label columns stay put.
  // CSS pins both at left:0 unless it knows the first column's width — measured here.
  const measureLabels = () => {
    document.querySelectorAll(".report-scroll table").forEach((t) => {
      const first = t.querySelector("tbody tr > .lbl:first-child, thead tr > .lbl:first-child");
      if (first) t.style.setProperty("--lbl1", first.getBoundingClientRect().width + "px");
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", measureLabels);
  else measureLabels();
  window.addEventListener("resize", measureLabels);
})();
