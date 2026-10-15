// Journal entry panel (Month page and the Planner drawer share the element ids) — Save (upsert; the first save after the month ends freezes the figures), Refreeze,
// a dirty-aware Save button and a leave guard. csrf.js stamps the token on every fetch.
(function () {
  const P = window.PLANNING;
  const $ = (s) => document.querySelector(s);
  const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) }).then((r) => r.json());

  const ta = $("#entry-body"), save = $("#entry-save"), status = $("#entry-status");
  const refreeze = $("#entry-refreeze"), stamp = $("#entry-stamp"), strip = $("#entry-figures");
  let original = ta.value;

  const money = (v, signed) => {
    if (v === null || v === undefined) return "—";
    const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : (v < 0 ? "−" : "");
    return sign + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
  };
  const pct = (v) => (v === null || v === undefined) ? "—" : Math.round(v * 100) + "%";

  function showFigures(fig, frozenAt) {
    strip.innerHTML = [
      ["Income", money(fig.income)], ["Spend", money(fig.expense)], ["Net", money(fig.net, true)],
      ["Rate", pct(fig.savings_rate)], ["Net worth", money(fig.net_worth)],
    ].map(([k, v]) => `<div>${k}<b>${v}</b></div>`).join("");
    stamp.textContent = frozenAt ? "Figures frozen " + frozenAt.slice(0, 16).replace("T", " ")
      : P.open ? "Figures live while the month is open" : "Figures live · frozen on first save";
    refreeze.hidden = !frozenAt;
  }
  // An entry of an open month has no frozen figures: the live preview stands in.
  const showEntry = (entry) => showFigures((entry && entry.figures) || P.preview, entry && entry.frozen_at);
  showEntry(P.entry);

  ta.addEventListener("input", () => { save.disabled = ta.value === original; });

  // A prompt chip appends its sentence to the entry and hides itself; the server decides
  // "addressed" from the saved body on the next render, so an unsaved insert comes back.
  const chips = $("#prompt-chips");
  if (chips) chips.addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    ta.value = ta.value.replace(/\s*$/, "") + (ta.value.trim() ? "\n\n" : "") + b.textContent.trim() + " ";
    b.remove();
    if (!chips.querySelector(".chip")) $("#prompts-card").hidden = true;
    ta.dispatchEvent(new Event("input")); ta.focus();
    ta.selectionStart = ta.selectionEnd = ta.value.length;
  });

  function doSave() {
    status.textContent = "Saving…"; save.disabled = true;
    post("/api/planning/entry/" + P.period, { body: ta.value })
      .then((d) => {
        if (!d.ok) { status.textContent = "Error: " + (d.error || "failed"); save.disabled = false; return; }
        original = ta.value; P.entry = d.entry; status.textContent = "✓ Saved";
        showEntry(d.entry);
      })
      .catch(() => { status.textContent = "Network error"; save.disabled = false; });
  }
  save.addEventListener("click", doSave);
  refreeze.addEventListener("click", () => {
    status.textContent = "Refreezing…";
    post("/api/planning/entry/" + P.period + "/refreeze")
      .then((d) => {
        if (!d.ok) { status.textContent = "Error: " + (d.error || "failed"); return; }
        P.entry = d.entry; status.textContent = "✓ Figures refrozen"; showEntry(d.entry);
      })
      .catch(() => { status.textContent = "Network error"; });
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); if (ta.value !== original) doSave(); }
  });
  window.addEventListener("beforeunload", (e) => { if (ta.value !== original) { e.preventDefault(); e.returnValue = ""; } });
})();
