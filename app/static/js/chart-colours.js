// The chart colours panel (_chart_colours.html): the picker and the hex field of each row
// stay in step, × puts a row back to its default, and every change is previewed at once —
// the token on <html> is rewritten and chartTheme.refresh() redraws the page's charts. Only
// Save keeps it; a reload without saving shows the stored colours again.
(function () {
  const panel = document.getElementById("chart-colours");
  if (!panel) return;
  const HEX = /^#[0-9a-f]{6}$/;
  const preview = (role, value) => {
    document.documentElement.style.setProperty("--chart-" + role, value);
    if (window.chartTheme) window.chartTheme.refresh();
  };
  panel.querySelectorAll(".chart-colour").forEach((row) => {
    const role = row.dataset.role, picker = row.querySelector("input[type=color]"), hex = row.querySelector(".chart-colour-hex");
    const set = (value) => { picker.value = value; hex.value = value; preview(role, value); };
    picker.addEventListener("input", () => set(picker.value));
    hex.addEventListener("change", () => {
      const v = hex.value.trim().toLowerCase();
      if (HEX.test(v)) set(v); else hex.value = picker.value;
    });
    row.querySelector(".chart-colour-default").addEventListener("click", () => set(row.dataset.default));
  });
})();
