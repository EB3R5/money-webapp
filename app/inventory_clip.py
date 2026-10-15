"""Inventory clipper — turn a live retailer product page into Item fields.

Two halves, both here so a field rule is declared once:

* `bookmarklet(base)` generates the `javascript:` bookmark. On a product page it
  harvests RAW strings off the live DOM (schema.org Product JSON-LD → og/meta →
  host-gated Amazon / IKEA selectors), base64url-encodes the payload and opens
  `{base}/inventory/clip#<payload>` — a popup on the app's own origin, so the
  session cookie applies and nothing cross-origin ever hits the API.
* The pure normalizers below turn that raw payload into stored-form Item fields
  (`scraped_fields`), a canonical URL for Link matching (`normalize_url`), and a
  Category suggestion against the live `inventoryCategories` names
  (`suggest_category`). They are plain functions — views/inventory_clip.py is
  the only impure caller — and tests/test_inventory_clip.py pins them.

Payload shape (every value a string, '' when missing):
    {url, domain, item_name, brand, model, sku, price, currency, color, size,
     dimensions_raw, dims: {width|height|depth|weight: {value, unit}|null},
     images: [url,...], category_hint: [breadcrumb,...], ld_category}
"""

import difflib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from .inventory_item import FIELD_NAMES

# --- URL ---------------------------------------------------------------------

_TRACKING_EXACT = {
    "ref", "ref_", "fbclid", "gclid", "yclid", "msclkid", "igshid", "srsltid", "_ga",
    "tag", "th", "psc", "spm", "keywords", "qid", "sr", "sprefix", "crid", "linkcode",
    "smid", "dib", "dib_tag", "mc_cid", "mc_eid", "cmpid", "cid", "clickid", "s", "language",
}
_TRACKING_PREFIX = ("utm_", "pf_rd_", "pd_rd_", "mc_", "dib", "ref_", "_hs", "hsa_")
_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?=[/?]|$)")


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in _TRACKING_EXACT or k.startswith(_TRACKING_PREFIX)


def normalize_url(url: str) -> str:
    """Canonical form for Link matching: lower-case scheme+host, no `www.`, no fragment,
    tracking params dropped, remaining params sorted, no trailing slash. Amazon product
    URLs collapse to `https://amazon.<tld>/dp/<ASIN>` (the rest of the path is SEO fluff).
    Applied to BOTH the stored Link and the incoming page URL, so old links still match."""
    if not url or not isinstance(url, str):
        return ""
    p = urlsplit(url.strip())
    if not p.netloc:
        return ""
    scheme = (p.scheme or "https").lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path or "/"
    if "amazon." in host:
        m = _ASIN_RE.search(path)
        if m:
            return f"https://{host}/dp/{m.group(1)}"
    params = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                    if not _is_tracking(k))
    path = path.rstrip("/")
    out = f"{scheme}://{host}{path}"
    if params:
        out += "?" + urlencode(params)
    return out


def domain_of(url: str) -> str:
    """Host without `www.` — the Item's Source."""
    try:
        host = urlsplit((url or "").strip()).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


# --- price -------------------------------------------------------------------

_NUM_RUN = re.compile(r"\d[\d.,\s ]*")


def _fmt_cost(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def to_cost_str(price, currency: str = "") -> str:
    """'$1,234.56' / '59,99 €' / '1.234,56' / 12 → plain number string for Unit_Cost
    (inventory is a keep_string collection). '' when nothing numeric is found."""
    if price is None or price == "":
        return ""
    if isinstance(price, bool):
        return ""
    if isinstance(price, (int, float)):
        return _fmt_cost(float(price))
    m = _NUM_RUN.search(str(price))
    if not m:
        return ""
    t = m.group(0).replace(" ", "").replace(" ", "").strip(".,")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):      # 1.234,56 — EU
            t = t.replace(".", "").replace(",", ".")
        else:                                # 1,234.56 — US
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:   # 59,99 / 1,5 — decimal comma
            t = parts[0] + "." + parts[1]
        else:                                        # 1,234 / 1,234,567 — thousands
            t = t.replace(",", "")
    elif "." in t:
        parts = t.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):   # 1.234 / 1.234.567
            t = t.replace(".", "")
    try:
        return _fmt_cost(float(t))
    except ValueError:
        return ""


# --- dimensions --------------------------------------------------------------

_UNIT_MAP = {
    "cmt": "cm", "mmt": "mm", "mtr": "m", "inh": "in", "ftq": "ft",
    "kgm": "kg", "grm": "g", "lbr": "lb", "onz": "oz",
    "centimeter": "cm", "centimeters": "cm", "centimetre": "cm", "centimetres": "cm",
    "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "millimetres": "mm",
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "inch": "in", "inches": "in", '"': "in", "feet": "ft", "foot": "ft",
    "kilogram": "kg", "kilograms": "kg", "gram": "g", "grams": "g",
    "pound": "lb", "pounds": "lb", "lbs": "lb", "ounce": "oz", "ounces": "oz",
}
_QV_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)(?:\s+(\d+)/(\d+))?\s*([a-zA-Z\"]*)")
_RAW_DIMS_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[x×X]\s*(\d+(?:[.,]\d+)?)\s*[x×X]\s*(\d+(?:[.,]\d+)?)"
    r"\s*([a-zA-Z\"]+)?")


def _unit(u) -> str:
    u = (u or "").strip().rstrip(".")
    return _UNIT_MAP.get(u.lower(), u.lower())


def _num(s: str) -> str:
    s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return s
    return str(int(v)) if v == int(v) else f"{v:g}"


def _quantity(qv):
    """{value, unit} | 'value' → (number_str, unit) or None. The value may itself
    carry the unit ('80 cm' — IKEA's spec rows)."""
    if qv in (None, "", {}):
        return None
    if isinstance(qv, dict):
        value, unit = qv.get("value"), qv.get("unit") or qv.get("unitText") or qv.get("unitCode") or ""
    else:
        value, unit = qv, ""
    if value in (None, ""):
        return None
    m = _QV_RE.match(str(value))
    if not m:
        return None
    n = m.group(1).replace(",", ".")
    if m.group(2) and m.group(3) and m.group(3) != "0":      # '31 1/2' (IKEA US)
        n = str(float(n) + int(m.group(2)) / int(m.group(3)))
    return _num(n), _unit(m.group(4) or unit)


def format_dimensions(dims: dict | None, raw: str = "") -> str:
    """'80×28×202 cm' from width/depth/height; a partial set becomes 'W 80 cm · H 202 cm';
    weight is appended ' · 12 kg'. Without structured values, a raw 'L x W x H unit'
    string (Amazon's spec table) is normalised into the same form; else raw, collapsed."""
    dims = dims or {}
    w, d, h = (_quantity(dims.get(k)) for k in ("width", "depth", "height"))
    wt = _quantity(dims.get("weight"))
    s = ""
    if w and d and h:
        units = {q[1] for q in (w, d, h) if q[1]}
        if len(units) <= 1:
            u = next(iter(units), "")
            s = f"{w[0]}×{d[0]}×{h[0]}" + (f" {u}" if u else "")
        else:
            s = "×".join(f"{q[0]} {q[1]}".strip() for q in (w, d, h))
    elif w or d or h:
        s = " · ".join(f"{lbl} {q[0]} {q[1]}".strip()
                       for lbl, q in (("W", w), ("D", d), ("H", h)) if q)
    else:
        raw = re.sub(r"\s+", " ", (raw or "")).strip()
        m = _RAW_DIMS_RE.search(raw)
        if m:
            u = _unit(m.group(4))
            s = f"{_num(m.group(1))}×{_num(m.group(2))}×{_num(m.group(3))}" + (f" {u}" if u else "")
        else:
            s = raw[:120]
    if wt:
        s = (s + " · " if s else "") + f"{wt[0]} {wt[1]}".strip()
    return s


# --- category ----------------------------------------------------------------

_GENERIC_HINTS = {"home", "homepage", "all", "products", "product", "shop", "all products",
                  "all categories", "categories", "back to results", "amazon", "ikea"}
_SPLIT_RE = re.compile(r"\s*(?:>|/|\||›|»|→)\s*")


def suggest_category(hints, ld_category: str = "", names=None) -> dict:
    """Pick an existing Category name for a page. Hints are tried most-specific first
    (breadcrumbs reversed, then the JSON-LD category path reversed); per hint: exact
    case-insensitive → substring either way → difflib close match (cutoff 0.6).
    Returns {"suggested": name|None, "candidates": [name, ...]} — candidates are the
    close-ish names (≤5) the picker should surface even when nothing was chosen."""
    names = [n for n in (names or []) if isinstance(n, str) and n.strip()]
    if not names:
        return {"suggested": None, "candidates": []}
    lower = {}
    for n in names:
        lower.setdefault(n.lower().strip(), n)
    keys = list(lower)
    long_keys = [k for k in keys if len(k) >= 4]   # fuzzy never lands on 'Art' from 'Party'

    ordered = [h for h in reversed(list(hints or [])) if isinstance(h, str) and h.strip()]
    ordered += [p for p in reversed(_SPLIT_RE.split(ld_category or "")) if p.strip()]

    suggested, candidates = None, []

    def add(name):
        if name not in candidates:
            candidates.append(name)

    for h in ordered:
        hl = re.sub(r"\s+", " ", h.lower()).strip()
        if hl in _GENERIC_HINTS or len(hl) < 3:
            continue
        hit = lower.get(hl)
        if not hit:
            for k in keys:
                if len(k) >= 4 and (hl in k or k in hl):
                    hit = lower[k]
                    break
        close = [lower[c] for c in difflib.get_close_matches(hl, long_keys, n=3, cutoff=0.6)]
        if hit:
            add(hit)
        for c in close:
            add(c)
        if suggested is None and (hit or close):
            suggested = hit or close[0]
            # keep scanning one more level only to fill candidates; the choice is made
            if len(candidates) >= 3:
                break
    return {"suggested": suggested, "candidates": candidates[:5]}


# --- payload → Item fields ---------------------------------------------------

def _t(v, limit: int = 500) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()[:limit]


def scraped_fields(payload: dict) -> dict:
    """The Item fields the popup diffs against the stored doc. Only names present in
    inventory_item.FIELD_NAMES survive, so the client can never post a non-editable key.
    Model falls back to the SKU/ASIN/article number. Link keeps the ORIGINAL url (it
    should open the exact page); matching uses normalize_url separately."""
    p = payload or {}
    url = _t(p.get("url"), 2000)
    out = {
        "Item_Name": _t(p.get("item_name")),
        "Brand": _t(p.get("brand"), 120),
        "Model": _t(p.get("model"), 120) or _t(p.get("sku"), 120),
        "Unit_Cost": to_cost_str(p.get("price"), _t(p.get("currency"), 8)),
        "Color": _t(p.get("color"), 120),
        "Size": _t(p.get("size"), 120),
        "Dimensions": format_dimensions(p.get("dims") if isinstance(p.get("dims"), dict) else {},
                                        _t(p.get("dimensions_raw"))),
        "Link": url,
        "Source": domain_of(url),
    }
    return {k: v for k, v in out.items() if k in FIELD_NAMES}


def image_candidates(payload: dict, limit: int = 8) -> list:
    """De-duplicated http(s) image URLs from the payload, best-first as the bookmarklet
    ordered them."""
    seen, out = set(), []
    for u in (payload or {}).get("images") or []:
        if not isinstance(u, str):
            continue
        u = u.strip()
        if not re.match(r"^https?://", u) or u in seen or len(u) > 1500:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out


# --- bookmarklet -------------------------------------------------------------

# Written as statements (no `//` comments — the lines are joined into one) using only
# single quotes, so the string survives an HTML href attribute and copy-paste. Every
# store-specific branch is host-gated and each selector falls back to the generic value.
_BOOKMARKLET_JS = r"""
(function(){
var H='__HOST__',B='__BASE__/inventory/clip#';
if(location.host==H){alert('Drag me to your bookmarks bar, then click me on a store product page.');return;}
function T(s){return (s==null?'':String(s)).replace(/\s+/g,' ').trim().slice(0,500);}
function m(p){var a=document.getElementsByTagName('meta');for(var k=0;k<a.length;k++){var e=a[k];if(e.getAttribute('property')==p||e.getAttribute('name')==p){var c=e.getAttribute('content');if(c)return T(c);}}return '';}
function q(s){try{return document.querySelector(s);}catch(e){return null;}}
function qa(s){try{return Array.prototype.slice.call(document.querySelectorAll(s));}catch(e){return [];}}
function tx(e){return e?T(e.textContent):'';}
function nm(x){return x?(typeof x=='string'?x:(x.name||'')):'';}
function qv(x){if(x==null||x==='')return null;if(typeof x=='object'){if(x.value==null)return null;return {value:String(x.value),unit:String(x.unitText||x.unitCode||'')};}return {value:String(x),unit:''};}
var L=null,BC=null,S=document.getElementsByTagName('script');
function walk(o){if(!o)return;if(Array.isArray(o)){o.forEach(walk);return;}if(typeof o!='object')return;if(o['@graph'])walk(o['@graph']);var t=o['@type'],ts=Array.isArray(t)?t:[t];if(!L&&ts.indexOf('Product')>=0)L=o;if(!BC&&ts.indexOf('BreadcrumbList')>=0)BC=o;}
for(var k=0;k<S.length;k++){if((S[k].getAttribute('type')||'')!='application/ld+json')continue;try{walk(JSON.parse(S[k].textContent));}catch(e){}}
var f=L&&L.offers;if(Array.isArray(f))f=f[0];if(f&&f.offers){f=Array.isArray(f.offers)?f.offers[0]:f.offers;}
var P={url:location.href,domain:location.host,
item_name:T((L&&L.name)||m('og:title')||document.title),
brand:T(nm(L&&L.brand)||m('og:brand')||m('product:brand')),
model:T(nm(L&&L.model)),
sku:T((L&&(L.sku||L.mpn||L.productID))||''),
price:T((f&&(f.price||f.lowPrice))||m('product:price:amount')||m('og:price:amount')),
currency:T((f&&f.priceCurrency)||m('product:price:currency')||m('og:price:currency')),
color:T(nm(L&&L.color)),size:T(nm(L&&L.size)),dimensions_raw:'',
dims:{width:qv(L&&L.width),height:qv(L&&L.height),depth:qv(L&&L.depth),weight:qv(L&&L.weight)},
images:[],category_hint:[],ld_category:T(nm(L&&L.category))};
var IM=[],AI=[];
function add(arr,u){if(!u||typeof u!='string')return;u=u.trim();if(u.indexOf('//')==0)u=location.protocol+u;if(u.indexOf('/')==0)u=location.origin+u;if(!/^https?:\/\//.test(u)||u.length>1500)return;if(arr.indexOf(u)<0)arr.push(u);}
function ai(u){add(IM,u);}function af(u){add(AI,u);}
function li(x){if(!x)return;if(Array.isArray(x)){x.forEach(li);return;}if(typeof x=='object'){ai(x.url||x.contentUrl);return;}ai(x);}
li(L&&L.image);ai(m('og:image'));ai(m('og:image:secure_url'));ai(m('twitter:image'));
if(BC&&BC.itemListElement){var els=Array.isArray(BC.itemListElement)?BC.itemListElement:[BC.itemListElement];els.forEach(function(e){var n=e&&(e.name||(e.item&&e.item.name));if(n)P.category_hint.push(T(n));});}
if(!P.category_hint.length){qa('nav[aria-label*=readcrumb] a,.breadcrumb a,.breadcrumbs a,[class*=readcrumb] a').forEach(function(a){var n=tx(a);if(n&&P.category_hint.indexOf(n)<0)P.category_hint.push(n);});}
var h=location.host;
if(h.indexOf('amazon.')>=0){
var e=q('#productTitle');if(tx(e))P.item_name=tx(e);
e=q('#bylineInfo');if(tx(e))P.brand=tx(e).replace(/^(Visit the |Brand: )/i,'').replace(/ Store$/i,'');
var PS=['#corePriceDisplay_desktop_feature_div .a-price[data-a-color=base] .a-offscreen','#corePriceDisplay_desktop_feature_div .a-offscreen','#corePrice_feature_div .a-offscreen','#apex_desktop .a-price .a-offscreen','#price_inside_buybox','#priceblock_ourprice','#priceblock_dealprice','#sns-base-price','.a-price .a-offscreen'],PT='';
for(var pk=0;pk<PS.length&&!PT;pk++){PT=tx(q(PS[pk]));}
if(!PT){var bw=q('#corePriceDisplay_desktop_feature_div')||q('#corePrice_feature_div')||q('#apex_desktop');if(bw){var wq=bw.querySelector('.a-price-whole'),fq=bw.querySelector('.a-price-fraction');if(wq)PT=wq.textContent.replace(/[^0-9]/g,'')+'.'+((fq&&fq.textContent.replace(/[^0-9]/g,''))||'00');}}
if(PT)P.price=PT;
var asin=(location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/)||[])[1];if(asin&&!P.sku)P.sku=asin;
var rows=[];qa('#productDetails_techSpec_section_1 tr,#productDetails_detailBullets_sections1 tr,#prodDetails tr').forEach(function(r){var th=r.querySelector('th'),td=r.querySelector('td');if(th&&td)rows.push([tx(th),tx(td)]);});
qa('#detailBullets_feature_div li').forEach(function(l){var t=tx(l).replace(/[\u200e\u200f]/g,'');var i=t.indexOf(':');if(i>0)rows.push([t.slice(0,i).trim(),t.slice(i+1).trim()]);});
function sp(re){for(var r=0;r<rows.length;r++){if(re.test(rows[r][0]))return rows[r][1].replace(/[\u200e\u200f]/g,'').trim();}return '';}
if(!P.model)P.model=sp(/item model number|model number|model name/i);
e=q('#variation_color_name .selection');P.color=tx(e)||P.color||sp(/^colou?r$/i);
e=q('#variation_size_name .selection');P.size=tx(e)||P.size||sp(/^size$/i);
P.dimensions_raw=sp(/product dimensions|item dimensions|package dimensions/i);
var wt=sp(/item weight/i);if(wt&&!P.dims.weight)P.dims.weight={value:wt,unit:''};
var im=q('#landingImage')||q('#imgBlkFront')||q('#main-image');
if(im){af(im.getAttribute('data-old-hires'));try{var dj=JSON.parse(im.getAttribute('data-a-dynamic-image')||'{}');Object.keys(dj).sort(function(a,b){return (dj[b][0]*dj[b][1])-(dj[a][0]*dj[a][1]);}).forEach(af);}catch(x){}af(im.getAttribute('src'));}
qa('#altImages img').forEach(function(i){var s=i.getAttribute('src')||'';if(s.indexOf('/images/I/')>=0)af(s.replace(/\._[^./]+_\./,'._SL1500_.'));});
var seen={};AI=AI.filter(function(u){var mm=u.match(/\/images\/I\/([^./]+)\./);var k=mm?mm[1]:u;if(seen[k])return false;seen[k]=1;return true;});
}
if(h.indexOf('ikea.')>=0){
var art=(location.pathname.match(/(\d{8})\/?$/)||[])[1];if(art&&!P.sku)P.sku=art;
var dr=[];qa('.pip-product-dimensions__measurement-wrapper,[class*=product-dimensions__measurement-wrapper]').forEach(function(w){var t=tx(w);var i=t.indexOf(':');if(i>0){var k=t.slice(0,i).trim().toLowerCase(),v=t.slice(i+1).trim();dr.push(t);if(k=='width'&&!P.dims.width)P.dims.width={value:v,unit:''};if(k=='depth'&&!P.dims.depth)P.dims.depth={value:v,unit:''};if(k=='height'&&!P.dims.height)P.dims.height={value:v,unit:''};if(k=='weight'&&!P.dims.weight)P.dims.weight={value:v,unit:''};}});
if(dr.length&&!P.dimensions_raw)P.dimensions_raw=dr.join(', ');
qa('.pip-media-grid img,img.pip-image,.pip-product-gallery img').forEach(function(i){var s=i.getAttribute('srcset')||'',best='',bw=0;s.split(',').forEach(function(p){var mm=p.trim().split(/\s+/);var w=parseInt(mm[1]||'0',10);if(w>bw){bw=w;best=mm[0];}});best=best||i.currentSrc||i.getAttribute('src')||'';if(best)af(best.replace(/([?&])f=[a-z]+/,'$1f=xl'));});
}
if(AI.length||IM.length<2){qa('img').filter(function(i){return i.naturalWidth>=300&&i.naturalHeight>=300&&!/\.svg|sprite|logo|icon/i.test(i.currentSrc||i.src||'');}).sort(function(a,b){return b.naturalWidth*b.naturalHeight-a.naturalWidth*a.naturalHeight;}).slice(0,3).forEach(function(i){ai(i.currentSrc||i.src);});}
IM=AI.concat(IM.filter(function(u){return AI.indexOf(u)<0;}));
P.images=IM.slice(0,8);P.category_hint=P.category_hint.slice(0,8);
var enc=btoa(unescape(encodeURIComponent(JSON.stringify(P)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
var w=window.open(B+enc,'money-clip','width=820,height=960');
if(!w)alert('Popup blocked - allow popups for this site and click again.');
})();
"""


def build_bookmarklet(js_source: str, base: str) -> str:
    """Join a bookmarklet's source into one `javascript:` line for the given app origin
    (e.g. 'http://127.0.0.1:8012'), filling __HOST__ / __BASE__. No double quotes anywhere
    in the output. Shared by every clipper (software_clip.software_bookmarklet)."""
    base = (base or "").rstrip("/")
    host = urlsplit(base).netloc
    js = "".join(line.strip() for line in js_source.strip().splitlines())
    js = js.replace("__HOST__", host).replace("__BASE__", base)
    if '"' in js:
        raise ValueError("bookmarklet must not contain double quotes")
    return "javascript:" + js


def bookmarklet(base: str) -> str:
    """The inventory clipper's bookmark for the given app origin."""
    return build_bookmarklet(_BOOKMARKLET_JS, base)
