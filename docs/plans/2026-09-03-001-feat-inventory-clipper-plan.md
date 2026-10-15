---
title: Inventory Clipper - Plan
type: feat
date: 2026-09-03
topic: inventory-clipper
artifact_contract: ce-unified-plan/v1
artifact_readiness: implemented
product_contract_source: dialogue
execution: code
---

# Inventory Clipper - Plan

## Goal Capsule

- **Objective:** Add or update an inventory Item straight from a store product page: a bookmarklet
  harvests the page (name, brand, model/SKU, price, color, size, dimensions, images, breadcrumbs)
  and opens a first-party popup where the user ticks which values to write. Update is the primary
  flow: the Item whose `Link` matches the page is preselected and every field is shown as
  current-vs-scraped with a checkbox.
- **Product authority:** This document. Decisions confirmed in dialogue 2026-09-03: bookmarklet +
  popup (not a Claude skill); auto-match on Link else search picker; per-field diff with
  checkboxes; scrape core + Model/SKU + Color/Size/Dimensions + Category suggestion; images must
  reliably attach.
- **Stop conditions:** none open.

## Product Contract

### Summary

`/inventory/clip/setup` hands out a `javascript:` bookmark bound to the app origin. Clicked on a
product page it scrapes the live DOM (schema.org Product JSON-LD → og/meta → host-gated Amazon
and IKEA selectors), base64url-encodes the raw strings and opens
`/inventory/clip#<payload>`. The popup runs on the app origin, so the TOTP session cookie applies
and no cross-origin request is ever made (a SameSite=lax cookie would not ride a cross-site POST,
which is why future-purchases' direct `/api/clip` shape was not copied).

### Key Decisions

- **Bookmarklet harvests raw strings; Python normalises.** Price, dimensions, URL canonicalisation
  and category fuzzy-matching live in `app/inventory_clip.py` where pytest can pin them. The popup
  JS is a renderer.
- **Field writes reuse the board's own endpoints.** `POST /api/inventory/row` and
  `POST /api/inventory/{id}` keep whitelisting, `Item_ID` minting, `Qty` defaults and dirty-diff
  semantics (ADR-0007) in one place; the clipper only adds read/prepare/search and image-attach
  routes.
- **Link matching is on a normalised URL.** `www.`, fragments, tracking params (`utm_*`, `ref`,
  `psc`, `th`, …) are dropped and Amazon URLs collapse to `/dp/<ASIN>`, applied to both the stored
  Link and the page URL, so old links still match.
- **Images: candidates, not one URL.** JSON-LD + og + store galleries (Amazon hi-res
  `data-old-hires` / dynamic-image, IKEA `srcset`/`?f=xl`) are offered as tickable thumbnails; the
  server downloads with a browser UA and the product page as Referer; failures fall back to a
  drag/paste/file upload zone that uses the existing multipart route.
- **Nothing is written until Apply.** Blank fields are pre-ticked, conflicts are opt-in, equal
  values are shown as "same" and cannot be ticked.

## Surfaces

| Piece | Path |
|---|---|
| Normalisers + bookmarklet generator | `app/inventory_clip.py` |
| Image download | `app/image_fetch.py` |
| Router (pages, prepare, search, fetch-image) | `app/routers/inventory_clip.py` |
| Popup + setup templates | `app/templates/inventory_clip.html`, `inventory_clip_setup.html` |
| Popup JS | `app/static/js/inventory-clip.js` |
| Byte-source image attach | `CardCollection.attach_image_bytes` in `app/card_collection.py` |
| Config | `CLIP_BASE_URL` in `app/config.py` (default: the setup page's own origin) |
| Tests | `tests/test_inventory_clip.py` |

## Verification

- `.venv/bin/python -m pytest` — 42 clipper tests (URL, price, dimensions incl. fractional inches,
  category suggestion, bookmarklet shape and host-gating, search, prepare, fetch-image with the
  download stubbed).
- Manual 2026-09-03 against a throwaway local Mongo: IKEA BILLY page → auto-matched the seeded
  Item by Link, blanks pre-ticked, 49→69 cost conflict opt-in, category "Furniture" suggested from
  breadcrumbs, 4 fields + 1 image written; Amazon Echo Dot page → title, byline brand, ASIN,
  buy-box price, hi-res image.

## Open Questions / Deferred

- Login redirects to `/`, so a logged-out popup loses its payload. A `next` parameter on
  `/login` carrying path + hash would fix it; deferred (the setup page says "stay logged in").
- The desktop app (`app/desktop.py`) binds a random port; mint the bookmark from the `:8010`
  uvicorn instance or set `CLIP_BASE_URL`.
- `_src` stays `"manual"` for clipped adds; `Link` + `Source` carry provenance.
