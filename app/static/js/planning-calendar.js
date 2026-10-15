// Calendar — place a shelf item by dragging it onto a month card (or clicking it and then a
// month card); drag a placed item to another month or back onto the shelf; ✕ on a placed
// item returns it to the shelf. Every write posts JSON then reloads so the server renders the
// new facts. Widths come from data-w (CSP: no style attributes in markup).
(function () {
  const $ = (s) => document.querySelector(s);
  document.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w + "%"; });
  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || "request failed");
    return data;
  }
  let selected = null;
  const hint = $("#cal-hint");
  function select(id) {
    selected = id;
    document.querySelectorAll("[data-shelf]").forEach((b) => b.classList.toggle("sel", b.dataset.shelf === id));
    document.querySelectorAll(".wm").forEach((c) => c.classList.toggle("drop", !!id));
    if (hint) hint.hidden = !id;
  }
  document.querySelectorAll("[data-shelf]").forEach((b) => b.addEventListener("click", () => select(selected === b.dataset.shelf ? null : b.dataset.shelf)));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") select(null); });

  // drag-and-drop (#184): items carry their flow id; a month card or the shelf is a target
  let dragging = null;
  document.querySelectorAll("[draggable]").forEach((el) => {
    el.addEventListener("dragstart", (e) => { dragging = el.dataset.id || el.dataset.shelf; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragging); el.classList.add("dragging"); });
    el.addEventListener("dragend", () => { dragging = null; el.classList.remove("dragging"); document.querySelectorAll(".over").forEach((c) => c.classList.remove("over")); });
  });
  async function dropTo(id, month) {
    try { await postJSON("/api/planning/flows/update", { id, month }); location.reload(); }
    catch (err) { alert("Could not move: " + err.message); }
  }
  document.querySelectorAll(".wm").forEach((card) => {
    card.addEventListener("dragover", (e) => { if (dragging) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; card.classList.add("over"); } });
    card.addEventListener("dragleave", () => card.classList.remove("over"));
    card.addEventListener("drop", (e) => { e.preventDefault(); const id = dragging || e.dataTransfer.getData("text/plain"); if (id) dropTo(id, card.dataset.month); });
  });
  const shelfCard = $("#shelf-card");
  if (shelfCard) {
    shelfCard.addEventListener("dragover", (e) => { if (dragging) { e.preventDefault(); shelfCard.classList.add("over"); } });
    shelfCard.addEventListener("dragleave", () => shelfCard.classList.remove("over"));
    shelfCard.addEventListener("drop", (e) => { e.preventDefault(); const id = dragging || e.dataTransfer.getData("text/plain"); if (id) dropTo(id, null); });
  }
  $("#wall").addEventListener("click", async (e) => {
    const un = e.target.closest("[data-unplace]");
    if (un) {
      try { await postJSON("/api/planning/flows/update", { id: un.dataset.unplace, month: null }); location.reload(); }
      catch (err) { alert("Could not unplace: " + err.message); }
      return;
    }
    const card = e.target.closest(".wm");
    if (!card || !selected) return;
    try { await postJSON("/api/planning/flows/update", { id: selected, month: card.dataset.month }); location.reload(); }
    catch (err) { alert("Could not place: " + err.message); }
  });
})();
