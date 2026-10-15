# Server-rendered Jinja + HTMX, with JS islands for grids — no SPA

The frontend is server-rendered Jinja templates extending one `base.html`, with HTMX for
navigation and small swaps. Interactivity that genuinely needs a client framework (the AG Grid
tables, the card-editor modals) is isolated as a per-page JavaScript island — one `static/js/<page>.js`
file wired up by data the template passes via a `<script>window.X = {{ ... | tojson }}</script>`
block.

We chose this over a single-page app because the app is a personal tool over mostly-tabular
data: server rendering keeps pages simple, debuggable, and printable, and the grids are the only
parts that need rich client behaviour. The islands stay deliberately small and are never
htmx-swapped.

_Consequence:_ each page owns its own JS file. The duplication this bred between similar pages
has since been consolidated: grids share `static/js/grid-factory.js` (makeGrid) and card editors
share `static/js/card-editor.js` (makeCardEditor); each page's island is now a thin declaration.

_Amendment 2026-10-08 (ADR-0024):_ the templates render through Django's Jinja2 backend, unchanged; HTMX was never actually loaded and is not part of the page model — pages are server-rendered and the JS islands call JSON views with `fetch`.
