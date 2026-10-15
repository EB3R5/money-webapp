// report-png.js — wires any [data-png-target] button to download the referenced element as
// a PNG via the html-to-image CDN lib. data-png-target is a CSS selector for the node to
// capture; data-png-name is the download filename. Shared by the server-rendered reports.
(function () {
  function wire() {
    document.querySelectorAll("[data-png-target]").forEach((btn) => {
      if (btn._pngWired) return;
      btn._pngWired = true;
      btn.addEventListener("click", () => {
        const node = document.querySelector(btn.getAttribute("data-png-target"));
        const name = btn.getAttribute("data-png-name") || "report.png";
        if (!node) { alert("Nothing to export yet."); return; }
        if (!window.htmlToImage) { alert("PNG library not loaded."); return; }
        const label = btn.textContent;
        btn.disabled = true;
        btn.textContent = "Rendering…";
        // White background (avoids black fill on transparent areas); 2x for a crisp image.
        window.htmlToImage
          .toPng(node, { backgroundColor: "#ffffff", pixelRatio: 2 })
          .then((url) => {
            const a = document.createElement("a");
            a.href = url; a.download = name; a.click();
          })
          .catch(() => alert("PNG export failed."))
          .finally(() => { btn.disabled = false; btn.textContent = label; });
      });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();
})();
