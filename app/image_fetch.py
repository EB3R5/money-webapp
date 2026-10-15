"""Download a product image URL to bytes, for the inventory clipper (app/inventory_clip.py).

Best-effort and never raises: any failure returns {"ok": False, "error": <readable>} so
the clip popup can show the message and offer a manual upload instead. Sends a desktop
browser UA and the product page as Referer — many retailer CDNs 403 a bare client or a
hotlink without a referer. Requires an image/* response, caps at 10 MB.

Ported from future-purchases/app/ogimage.py:download_image (the og:image parsing half is
not needed here — the bookmarklet already harvested the candidate URLs off the live DOM)."""

import re

import httpx

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
TIMEOUT = 10.0
MAX_BYTES = 10 * 1024 * 1024        # 10 MB cap


def download_image(url: str, referer: str | None = None, *, client: httpx.Client = None) -> dict:
    """{"ok": True, "data", "content_type", "filename"} or {"ok": False, "error"}."""
    if not url or not re.match(r"^https?://", url.strip()):
        return {"ok": False, "error": "no image url"}
    url = url.strip()
    # Prefer classic formats: some CDNs (IKEA) content-negotiate to AVIF when offered.
    headers = {"User-Agent": BROWSER_UA,
               "Accept": "image/jpeg,image/png,image/webp;q=0.9,image/*;q=0.8,*/*;q=0.5"}
    if referer and re.match(r"^https?://", referer):
        headers["Referer"] = referer
    own = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=TIMEOUT)
    try:
        img = c.get(url, headers=headers)
        img.raise_for_status()
        ct = (img.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not ct.startswith("image/"):
            return {"ok": False, "error": f"link did not return an image ({ct or 'unknown type'})"}
        data = img.content
        if len(data) > MAX_BYTES:
            return {"ok": False, "error": "image too large (over 10 MB)"}
        if not data:
            return {"ok": False, "error": "empty image"}
        filename = (url.rsplit("/", 1)[-1].split("?")[0] or "image")[:120]
        return {"ok": True, "data": data, "content_type": ct, "filename": filename}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"image fetch returned HTTP {e.response.status_code}"}
    except httpx.RequestError as e:
        return {"ok": False, "error": f"could not fetch image ({type(e).__name__})"}
    except Exception as e:
        return {"ok": False, "error": f"image fetch failed ({type(e).__name__})"}
    finally:
        if own:
            c.close()
