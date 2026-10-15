// inventory-sheet.js — the Item sheet's "Export bundle" button.
//
// Two steps behind one click: (1) capture #item-sheet as a PNG in the browser with the
// same html-to-image lib the report PNG buttons use, (2) POST it to
// /api/inventory/{id}/export and download the zip the server builds (item.md + card.png
// + photos/). The PNG is optional server-side — if the capture fails we still export,
// so a rendering hiccup never blocks getting the photos and Markdown out.
(function () {
  const btn = document.getElementById("sheet-export");
  const status = document.getElementById("sheet-status");
  const sheet = document.getElementById("item-sheet");
  if (!btn || !sheet || !window.SHEET) return;

  const say = (msg) => { status.textContent = msg || ""; };

  async function capturePng() {
    if (!window.htmlToImage) return null;
    try {
      // style: the sheet is centred with `margin: 0 auto`; the clone must drop that or the
      // capture keeps the left offset and clips the right edge.
      const url = await window.htmlToImage.toPng(sheet, {
        backgroundColor: "#ffffff", pixelRatio: 2, style: { margin: "0" },
      });
      return await (await fetch(url)).blob();
    } catch (e) {
      return null;
    }
  }

  function download(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  }

  function filenameFrom(res) {
    const cd = res.headers.get("Content-Disposition") || "";
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    if (star) { try { return decodeURIComponent(star[1]); } catch (e) { /* fall through */ } }
    const plain = /filename="([^"]+)"/i.exec(cd);
    return plain ? plain[1] : (window.SHEET.title || "item") + ".zip";
  }

  btn.addEventListener("click", async () => {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Rendering…";
    say("");
    try {
      const png = await capturePng();
      if (!png) say("PNG capture failed — exporting without card.png.");
      btn.textContent = "Bundling…";
      const fd = new FormData();
      if (png) fd.append("png", png, "card.png");
      const res = await fetch("/api/inventory/" + encodeURIComponent(window.SHEET.docId) + "/export",
                              { method: "POST", body: fd });
      if (!res.ok) throw new Error("HTTP " + res.status);
      download(await res.blob(), filenameFrom(res));
      say(png ? "Exported." : status.textContent + " Exported.");
    } catch (e) {
      say("Export failed: " + (e && e.message ? e.message : e));
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  });
})();
