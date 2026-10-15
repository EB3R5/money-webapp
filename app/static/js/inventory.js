// Inventory adapter — feeds makeCardEditor (app/static/js/card-editor.js) the
// inventory endpoints (incl. create + delete) and the derived Value = Qty × Unit_Cost.
//
// Chained selects: Category → Subcategory → Item Type. On modal open the three text
// inputs get a <select> in front of them, filled from /api/inventory/taxonomy
// (inventoryCategories grouped by Group, plus the values Items already use). Picking an
// option writes it into the original input — which stays the form's value carrier, so
// the editor's dirty-diff save is untouched — and refills the dependants. "＋ New…"
// reveals the text input for a value that isn't in the list yet.
(function () {
  const num = (v) => { const n = parseFloat(String(v).replace(/[$,]/g, "")); return isNaN(n) ? 0 : n; };

  const CHAIN = ["Category", "Subcategory", "Item_Type"];
  const NEW = "__new__";
  let taxonomy = null, loading = null;
  const loadTaxonomy = () => {
    if (!loading) loading = fetch("/api/inventory/taxonomy").then((r) => r.ok ? r.json() : null)
      .then((t) => { taxonomy = t; return t; }).catch(() => null);
    return loading;
  };
  loadTaxonomy();   // prefetch so the first modal open is instant

  // Options for level `idx`, given the current parent values in the form.
  function optionsFor(form, idx) {
    if (idx === 0) return taxonomy.groups.map((g) => ({ label: g.name, items: g.categories }));
    const cat = form.elements.Category.value.trim();
    const subs = taxonomy.tree[cat] || {};
    if (idx === 1) return [{ label: null, items: Object.keys(subs) }];
    const sub = form.elements.Subcategory.value.trim();
    return [{ label: null, items: subs[sub] || [] }];
  }

  function buildChain(form) {
    const selects = {};
    CHAIN.forEach((name, idx) => {
      const input = form.elements[name];
      if (!input) return;
      const field = input.closest(".field");
      let sel = field.querySelector("select.tax-select");
      if (!sel) {
        sel = document.createElement("select");
        sel.className = "tax-select";
        field.insertBefore(sel, input);
        sel.addEventListener("change", () => {
          if (sel.value === NEW) { input.hidden = false; input.value = ""; input.focus(); }
          else { input.hidden = true; input.value = sel.value; }
          refill(idx + 1);
        });
        // A typed "new" value changes what the dependants may offer (nothing yet).
        input.addEventListener("input", () => refill(idx + 1));
      }
      selects[name] = sel;
    });

    function refill(from) {
      for (let i = from; i < CHAIN.length; i++) {
        const name = CHAIN[i], sel = selects[name], input = form.elements[name];
        if (!sel) continue;
        const cur = input.value.trim();
        const groups = optionsFor(form, i);
        const known = groups.some((g) => g.items.includes(cur));
        sel.innerHTML = "";
        sel.appendChild(new Option("—", ""));
        groups.forEach((g) => {
          if (!g.items.length) return;
          const parent = g.label ? document.createElement("optgroup") : sel;
          if (g.label) parent.label = g.label;
          g.items.forEach((v) => parent.appendChild(new Option(v, v)));
          if (g.label) sel.appendChild(parent);
        });
        sel.appendChild(new Option("＋ New…", NEW));
        // A stored value the list doesn't know (older data, or a parent just changed)
        // stays visible as free text rather than being silently blanked.
        if (cur && !known) { sel.value = NEW; input.hidden = false; }
        else { sel.value = cur; input.hidden = true; }
      }
    }
    refill(0);
  }

  makeCardEditor({
    ...window.CARD,
    endpoint: "/api/inventory",
    createUrl: "/api/inventory/row",
    deleteUrl: "/api/inventory/delete",
    amount: (i) => Math.round(num(i.Qty) * num(i.Unit_Cost) * 100) / 100,
    subtitle: (i) => {
      const base = i.Brand || i.Subcategory || i.Item_Type || "";
      return base + (i.Qty && String(i.Qty) !== "1" ? " · ×" + i.Qty : "");
    },
    onModalOpen: (mode, item, form) => {
      loadTaxonomy().then((t) => { if (t) buildChain(form); });
      // The sheet needs a saved item; hide the action while creating.
      const sheetBtn = document.getElementById("card-sheet");
      if (sheetBtn) sheetBtn.hidden = mode !== "edit";
    },
    extraActions: [{
      id: "card-sheet",
      // Same-window navigation: the desktop (pywebview) window has no tabs.
      handler: (id) => { if (id) window.location = "/inventory/" + encodeURIComponent(id) + "/sheet"; },
    }],
  });
})();
