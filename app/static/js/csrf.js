// CSRF: every same-origin request that is not GET/HEAD/OPTIONS carries the session's
// token (from <meta name="csrf-token">) as X-CSRF-Token. Wrapping fetch once here means
// no page script has to remember; forms that post without JS carry a hidden field.
(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.content : "";
  if (!token || !window.fetch) return;
  const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);
  const origin = window.location.origin;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    const sameOrigin = url.startsWith("/") || url.startsWith(origin) || !/^[a-z]+:/i.test(url);
    if (!SAFE.has(method) && sameOrigin) {
      init = Object.assign({}, init || {});
      const headers = new Headers(init.headers || (input && input.headers) || {});
      if (!headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", token);
      init.headers = headers;
    }
    return nativeFetch(input, init);
  };
})();
