// Accounts adapter — feeds makeCardEditor (app/static/js/card-editor.js) the
// accounts endpoints (incl. create + delete) and the two tiny derivations
// (amount, subtitle), plus the bespoke "Add to Balances" action.
//
// Create mode is type-aware: the modal opens with only the "Account Kind" select
// visible and Save disabled; picking a type reveals that type's fields. Switching
// type clears values of fields leaving the visible set, so the create payload's
// omit-hidden-empty behavior holds (no stale value resurfaces).
(function () {
  const num = (v) => {
    if (v == null || v === "") return null;
    const n = parseFloat(String(v).replace(/[$,]/g, ""));
    return isNaN(n) ? null : n;
  };

  const CFG = window.CARD.extra || {};
  const TYPE_FIELD = CFG.typeField || "Account Kind";
  const TYPES = CFG.types || {};
  const EDIT_FIELDS = CFG.editFields || [];
  const ALL_FIELDS = (window.CARD.fields || []).map((f) => f.name);

  let mode = "edit";
  let cardForm = null;

  const labelOf = (name) =>
    document.querySelector('.field[data-field="' + CSS.escape(name) + '"]');

  const saveBtn = () =>
    document.querySelector("#card-form button[type='submit']");

  // Show exactly `names` (+ the type select when asked); in create mode, clear the
  // value of any field leaving visibility so hidden-but-filled can't happen.
  function setVisible(names, withTypeField) {
    ALL_FIELDS.forEach((n) => {
      const label = labelOf(n);
      if (!label) return;
      const show = names.includes(n) || (withTypeField && n === TYPE_FIELD);
      if (!show && mode === "create" && cardForm) {
        const el = cardForm.elements[n];
        if (el) el.value = "";
      }
      label.hidden = !show;
    });
  }

  function onTypeChange() {
    const kind = cardForm.elements[TYPE_FIELD].value;
    const fields = TYPES[kind];
    setVisible(fields || [], true);
    const btn = saveBtn();
    if (btn) btn.disabled = !fields;
  }

  const LINKED = CFG.linked || {};                 // {"Common stock": "portfolio", ...}
  const LINKED_EDITABLE = CFG.linkedEditable || [];
  const OWNING_PAGE = { portfolio: ["Investments", "/investments"], credit: ["Credit", "/credit"] };

  // Archive/Reopen replaces Delete for linked cards: one action closes/restores the
  // card together with its detail record; balance history is untouched.
  function lifecycleBtn() {
    let b = document.getElementById("card-lifecycle");
    if (!b) {
      b = document.createElement("button");
      b.type = "button";
      b.id = "card-lifecycle";
      b.className = "btn-secondary";
      const cancel = document.getElementById("card-cancel");
      if (cancel) cancel.parentNode.insertBefore(b, cancel);
    }
    return b;
  }

  function setLifecycle(item) {
    const btn = lifecycleBtn();
    const closed = (item.Status || "").toLowerCase() === "closed";
    btn.textContent = closed ? "Reopen" : "Archive";
    btn.hidden = false;
    btn.onclick = () => {
      const verb = closed ? "reopen" : "archive";
      if (!closed && !confirm('Archive "' + item.Account + '"? It closes here and on its owning page; balance history is kept.')) return;
      fetch("/api/accounts/" + verb, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: item._id }),
      })
        .then((r) => r.json())
        .then((d) => { if (d.ok) window.location.reload(); })
        .catch(() => {});
    };
  }

  function owningLink() {
    let a = document.getElementById("card-owning-link");
    if (!a) {
      a = document.createElement("a");
      a.id = "card-owning-link";
      a.className = "muted";
      a.style.marginLeft = "8px";
      const idLine = document.querySelector(".acct-id-line");
      if (idLine) idLine.appendChild(a);
    }
    return a;
  }

  function onModalOpen(m, item, form) {
    mode = m;
    cardForm = form;
    const btn = saveBtn();
    const balanceBtn = document.getElementById("card-add-balance");
    const deleteBtn = document.getElementById("card-delete");
    const link = owningLink();
    const kind = item && LINKED[item["Account Kind"]];

    if (m === "create") {
      setVisible([], true);            // only the type select until a type is chosen
      if (btn) btn.disabled = true;
      if (balanceBtn) balanceBtn.hidden = true;
      link.hidden = true;
      lifecycleBtn().hidden = true;
      return;
    }

    setVisible(EDIT_FIELDS, false);
    if (btn) btn.disabled = false;
    // Linked cards: detail record owns the value — lock type-owned fields, hide the
    // manual stamp + delete (archive replaces delete for linked), show the owning page.
    ALL_FIELDS.forEach((n) => {
      const el = form.elements[n];
      if (el) el.disabled = !!kind && !LINKED_EDITABLE.includes(n);
    });
    if (balanceBtn) balanceBtn.hidden = !!kind;
    if (deleteBtn && kind) deleteBtn.hidden = true;
    if (kind) {
      const [label, href] = OWNING_PAGE[kind];
      link.textContent = "Manage on " + label + " →";
      link.href = href;
      link.hidden = false;
      setLifecycle(item);
    } else {
      link.hidden = true;
      lifecycleBtn().hidden = true;
    }
  }

  function addToBalances(currentId, statusEl, item) {
    if (!currentId) return;
    const amt = item && item.Amount;
    statusEl.textContent = "Adding snapshot…";
    fetch("/api/balances/from-account/" + encodeURIComponent(currentId), { method: "POST" })
      .then((r) => r.json())
      .then((d) => {
        statusEl.textContent = d.ok
          ? "✓ Added to Balances" + (amt == null || amt === "" ? " (no amount set)" : "")
          : "Error: " + (d.error || "failed");
      })
      .catch(() => { statusEl.textContent = "Network error"; });
  }

  makeCardEditor({
    ...window.CARD,
    endpoint: "/api/accounts",
    createUrl: "/api/accounts/row",
    deleteUrl: "/api/accounts/delete",
    amount: (i) => num(i.Amount),
    subtitle: (i) => i.Category || "",
    onModalOpen: onModalOpen,
    extraActions: [{ id: "card-add-balance", handler: addToBalances }],
  });

  const typeSelect = document.querySelector('#card-form [name="' + TYPE_FIELD + '"]');
  if (typeSelect) typeSelect.addEventListener("change", onTypeChange);

  // Unlinked feed accounts strip (app/simplefin/link.py): each action posts, then the page
  // reloads so the strip and the cards re-render from the server.
  const strip = document.getElementById("feed-strip");
  const ignoredBox = document.getElementById("feed-ignored");
  const feedStatus = document.getElementById("feed-status");
  const post = (url, body) => fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).then((r) => r.json().then((d) => ({ ok: r.ok && d.ok !== false, d })));
  const act = (url, body) => post(url, body).then(({ ok, d }) => {
    if (ok) { window.location.reload(); return; }
    if (feedStatus) feedStatus.textContent = (d && d.error) || "failed";
  });
  (strip ? Array.from(strip.querySelectorAll(".feed-row")) : []).forEach((row) => {
    const feedId = row.dataset.feedId;
    row.querySelector(".feed-link").addEventListener("click", () => {
      const cardId = row.querySelector(".feed-card").value;
      if (!cardId) { if (feedStatus) feedStatus.textContent = "pick a card to link to"; return; }
      act("/api/accounts/link", { feed_id: feedId, card_id: cardId });
    });
    row.querySelector(".feed-promote").addEventListener("click", () => {
      const kind = row.querySelector(".feed-kind").value;
      if (!kind) { if (feedStatus) feedStatus.textContent = "pick a kind to promote as"; return; }
      act("/api/accounts/promote", { feed_id: feedId, kind });
    });
    row.querySelector(".feed-ignore").addEventListener("click", () => {
      if (!confirm("Ignore this feed account? Its rows are removed and the feed skips it from now on.")) return;
      act("/api/accounts/ignore", { feed_id: feedId });
    });
  });
  (ignoredBox ? Array.from(ignoredBox.querySelectorAll(".feed-row")) : []).forEach((row) => {
    row.querySelector(".feed-unignore").addEventListener("click", () =>
      act("/api/accounts/unignore", { feed_id: row.dataset.feedId }));
  });
})();
