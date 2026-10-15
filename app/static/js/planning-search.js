// Planning pages — an instant filter over every element carrying data-search (pins, chips,
// calendar items, shelf entries, planned rows, income rows): non-matching ones are hidden,
// the structure around them stays, a note says when nothing is left, and the term rides in
// ?q= so a reload keeps it. search.js holds the rule shared with the card boards.
(function () {
  const box = document.getElementById("plan-search");
  if (!box || !window.searchTokens) return;
  const items = Array.from(document.querySelectorAll("[data-search]"));
  const note = document.getElementById("plan-no-match");
  function apply() {
    const toks = window.searchTokens(box.value);
    let shown = 0;
    items.forEach((el) => {
      const hit = window.searchHit(["s"], { s: el.dataset.search }, toks);
      el.hidden = !hit;
      if (hit) shown += 1;
    });
    if (note) note.hidden = shown > 0 || items.length === 0;
    try {
      const url = new URL(window.location.href);
      if (box.value.trim()) url.searchParams.set("q", box.value.trim()); else url.searchParams.delete("q");
      history.replaceState(null, "", url.pathname + (url.search || ""));
    } catch (e) { /* no history in some embeds */ }
  }
  box.addEventListener("input", apply);
  box.addEventListener("keydown", (e) => { if (e.key === "Escape") { box.value = ""; apply(); } });
  apply();
})();
