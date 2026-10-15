"""Software clipping — the pure half: a URL router, deterministic mappers for the
registries that serve open JSON (GitHub, PyPI, npm, the iTunes Lookup API,
formulae.brew.sh), the mapper for what the bookmarklet harvests off a generic page
(Open Graph + schema.org SoftwareApplication JSON-LD), and the one httpx shell that
turns a source key into registry facts.

`route` and every `fields_from_*` are pure (URL / JSON / payload -> wire dict, see
software_item.WIRE) and unit-tested against recorded responses; `fetch_by_source_key`
is sync, takes an injectable client and never raises (same shape as
image_fetch.download_image). No HTML is parsed server-side — the bookmarklet reads the
live DOM — and no AI anywhere: every field comes from a documented API or the page's own
markup. The bookmarklet (software_bookmarklet) shares inventory_clip's line builder.
The router (app/views/software_clip.py) is the only impure caller.

Ported from future-purchases/app/software_clip.py minus its BeautifulSoup page parser."""

import re
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from .config import GITHUB_TOKEN
from .inventory_clip import build_bookmarklet
from .image_fetch import BROWSER_UA, TIMEOUT
from .software_item import split_source_key

# Sources whose truth is the local machine, not a registry: nothing to fetch remotely.
LOCAL_SOURCES = {"pacman", "aur", "cargo", "pipx", "uv", "mise"}

# github.com/{first} paths that are not a user/org.
_GITHUB_RESERVED = {"settings", "orgs", "marketplace", "features", "topics", "login", "explore",
                    "trending", "sponsors", "about", "pricing", "apps", "collections", "events",
                    "notifications", "search", "new", "issues", "pulls", "codespaces", "site",
                    "security", "enterprise", "team", "customer-stories", "readme", "join"}

_GITHUB_REPO_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/\s#?]+)/([^/\s#?]+)")


def github_repo_from_url(url):
    """'https://github.com/owner/repo/…' -> 'owner/repo' | None (pure; reused by the
    PyPI/npm/brew mappers to turn a project URL into a repo_url)."""
    if not isinstance(url, str):
        return None
    m = _GITHUB_REPO_RE.match(url.strip())
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if owner.lower() in _GITHUB_RESERVED:
        return None
    repo = repo[:-4] if repo.endswith(".git") else repo
    return f"{owner}/{repo}" if owner and repo else None


def route(url: str):
    """URL -> (source, key) for a registry we can fetch, else None (generic page).
    Keys are what the registry's JSON API is addressed by."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return None
    host = (p.netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host
    parts = [s for s in p.path.split("/") if s]

    if host == "github.com":
        repo = github_repo_from_url(url)
        return ("github", repo) if repo else None
    if host == "pypi.org" and len(parts) >= 2 and parts[0] in ("project", "p"):
        return ("pypi", parts[1])
    if host == "npmjs.com" and len(parts) >= 2 and parts[0] == "package":
        if parts[1].startswith("@") and len(parts) >= 3:
            return ("npm", parts[1] + "/" + parts[2])
        return ("npm", parts[1])
    if host == "apps.apple.com":
        m = re.search(r"/id(\d+)", p.path)
        return ("appstore", m.group(1)) if m else None
    if host == "formulae.brew.sh" and len(parts) >= 2 and parts[0] in ("formula", "cask"):
        token = parts[1][:-5] if parts[1].endswith(".html") else parts[1]
        return ("brew", f"{parts[0]}:{token}")
    if host == "marketplace.visualstudio.com" and parts[:1] == ["items"]:
        name = (parse_qs(p.query).get("itemName") or [None])[0]
        return ("vscode", name) if name else None
    return None


def fetchable(source: str) -> bool:
    """Whether a source has a JSON API we call (local managers and the VS Code
    Marketplace, which documents no read API, do not)."""
    return bool(source) and source not in LOCAL_SOURCES and source != "vscode"


# --- mappers: registry JSON -> wire dict ------------------------------------------

def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [])}


def fields_from_github(repo: dict, latest_release=None) -> dict:
    lic = repo.get("license") or {}
    spdx = lic.get("spdx_id") if isinstance(lic, dict) else None
    if spdx in ("NOASSERTION", "null"):
        spdx = None
    owner = repo.get("owner") or {}
    return _clean({
        "name": repo.get("name"),
        "vendor": owner.get("login"),
        "description": repo.get("description"),
        "homepage": repo.get("homepage") or repo.get("html_url"),
        "repo_url": repo.get("html_url"),
        "license_id": spdx,
        "license_type": "oss" if spdx else None,
        "stars": repo.get("stargazers_count"),
        "topics": repo.get("topics") or None,
        "archived": repo.get("archived"),
        "version_latest": (latest_release or {}).get("tag_name"),
        "kind": "library",
        "image_url": owner.get("avatar_url"),
    })


def fields_from_pypi(j: dict) -> dict:
    info = j.get("info") or {}
    urls = info.get("project_urls") or {}
    repo = None
    for k in ("Source", "Repository", "Code", "GitHub", "Source Code", "Homepage"):
        r = github_repo_from_url(urls.get(k))
        if r:
            repo = f"https://github.com/{r}"
            break
    lic = info.get("license_expression") or info.get("license")
    if lic and len(lic) > 64:          # some packages paste the whole license text here
        lic = None
    return _clean({
        "name": info.get("name"),
        "vendor": info.get("author"),
        "description": info.get("summary"),
        "homepage": info.get("home_page") or urls.get("Homepage") or urls.get("Documentation"),
        "repo_url": repo,
        "license_id": lic,
        "license_type": "oss" if lic else None,
        "version_latest": info.get("version"),
        "kind": "library",
    })


def _git_url_to_https(u):
    if not isinstance(u, str):
        return None
    u = u.strip()
    u = u[4:] if u.startswith("git+") else u
    u = re.sub(r"^git@github\.com:", "https://github.com/", u)
    u = re.sub(r"^git://", "https://", u)
    u = u[:-4] if u.endswith(".git") else u
    return u or None


def fields_from_npm(j: dict) -> dict:
    repo = j.get("repository")
    repo_url = _git_url_to_https(repo.get("url") if isinstance(repo, dict) else repo)
    author = j.get("author")
    vendor = author.get("name") if isinstance(author, dict) else (author if isinstance(author, str) else None)
    if not vendor:
        m = j.get("maintainers") or []
        vendor = (m[0].get("name") if m and isinstance(m[0], dict) else None)
    lic = j.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type")
    return _clean({
        "name": j.get("name"),
        "vendor": vendor,
        "description": j.get("description"),
        "homepage": j.get("homepage") or repo_url,
        "repo_url": repo_url,
        "license_id": lic,
        "license_type": "oss" if lic else None,
        "version_latest": (j.get("dist-tags") or {}).get("latest"),
        "kind": "library",
    })


def fields_from_itunes(j: dict) -> dict:
    results = j.get("results") or []
    if not results:
        return {}
    r = results[0]
    price = r.get("price")
    paid = isinstance(price, (int, float)) and price > 0
    return _clean({
        "name": r.get("trackName"),
        "vendor": r.get("sellerName"),
        "description": r.get("description"),
        "homepage": r.get("sellerUrl"),
        "link": r.get("trackViewUrl"),
        "cost": price if paid else None,
        "currency": r.get("currency") if paid else None,
        "billing_cadence": "one_time" if paid else None,
        "license_type": "perpetual" if paid else "free",
        "version_latest": r.get("version"),
        "bundle_id": r.get("bundleId"),
        "category": r.get("primaryGenreName"),
        "kind": "app",
        "image_url": r.get("artworkUrl512") or r.get("artworkUrl100"),
    })


def fields_from_brew(j: dict, sub: str) -> dict:
    """sub is 'formula' or 'cask' (the key's first segment)."""
    gh = github_repo_from_url(j.get("homepage"))
    repo_url = f"https://github.com/{gh}" if gh else None
    if sub == "cask":
        names = j.get("name") or []
        return _clean({
            "name": names[0] if names else j.get("token"),
            "description": j.get("desc"),
            "homepage": j.get("homepage"),
            "repo_url": repo_url,
            "version_latest": j.get("version"),
            "kind": "app",
        })
    lic = j.get("license")
    return _clean({
        "name": j.get("name"),
        "description": j.get("desc"),
        "homepage": j.get("homepage"),
        "repo_url": repo_url,
        "license_id": lic,
        "license_type": "oss" if lic else None,
        "version_latest": (j.get("versions") or {}).get("stable"),
        "kind": "cli",
    })


# --- the generic page: what the bookmarklet harvested ------------------------------

_TITLE_NOISE = re.compile(r"^(GitHub - |PyPI · |npm: )", re.I)


def clean_title(title):
    """'GitHub - owner/repo: A thing' -> 'A thing'; strips the registry prefixes."""
    if not isinstance(title, str):
        return None
    t = _TITLE_NOISE.sub("", title.strip())
    m = re.match(r"^[\w.-]+/[\w.-]+:\s*(.+)$", t)
    if m:
        t = m.group(1)
    return t.strip() or None


def _name_of(x):
    """A schema.org value that may be a string or a {name: …} node."""
    if isinstance(x, dict):
        x = x.get("name")
    return x.strip() if isinstance(x, str) and x.strip() else None


def _first_offer(app: dict):
    o = app.get("offers")
    if isinstance(o, list):
        o = next((x for x in o if isinstance(x, dict)), None)
    return o if isinstance(o, dict) else {}


def _image_of(app: dict):
    img = app.get("image") or app.get("screenshot")
    if isinstance(img, list):
        img = next((x for x in img if x), None)
    if isinstance(img, dict):
        img = img.get("url") or img.get("contentUrl")
    return img if isinstance(img, str) and img.strip() else None


def fields_from_payload(payload: dict) -> dict:
    """Bookmarklet payload -> wire dict for a page no registry answers for. The payload
    (see _SOFTWARE_JS below) carries `url`, `title`, `og_title`,
    `og_description`, `og_image` and `ld_app` — the first SoftwareApplication /
    WebApplication / MobileApplication JSON-LD node, or null. JSON-LD wins over OG,
    OG over document.title; the image is made absolute against the page URL."""
    if not isinstance(payload, dict):
        return {}
    url = (payload.get("url") or "").strip()
    app = payload.get("ld_app") if isinstance(payload.get("ld_app"), dict) else {}
    offer = _first_offer(app)
    price = offer.get("price")
    priced = price not in (None, "", 0, "0")
    image = _image_of(app) or payload.get("og_image")
    out = _clean({
        "name": _name_of(app.get("name")) or clean_title(payload.get("og_title"))
                or clean_title(payload.get("title")),
        "vendor": _name_of(app.get("author")) or _name_of(app.get("publisher")),
        "description": _name_of({"name": app.get("description")}) or
                       (payload.get("og_description") or "").strip() or None,
        "category": _name_of(app.get("applicationCategory")),
        "version_latest": _name_of({"name": app.get("softwareVersion")}),
        "cost": price if priced else None,
        "currency": offer.get("priceCurrency") if priced else None,
        "billing_cadence": "one_time" if priced else None,
        "image_url": urljoin(url, image) if (image and url) else image,
        "link": url or None,
    })
    return out


# --- the shell ---------------------------------------------------------------------

def _client(client):
    own = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=TIMEOUT,
                               headers={"User-Agent": BROWSER_UA})
    return c, own


def _get_json(c, url, headers=None):
    r = c.get(url, headers=headers or {})
    r.raise_for_status()
    return r.json()


def fetch_by_source_key(sk: str, *, client: httpx.Client = None):
    """'github:owner/repo' etc. -> {"fields": wire dict, "image_url"} | None.
    None for local-only / unfetchable sources and on any failure. Never raises."""
    parsed = split_source_key(sk)
    if not parsed:
        return None
    source, key = parsed
    if not fetchable(source):
        return None
    c, own = _client(client)
    try:
        if source == "github":
            hdr = {"Accept": "application/vnd.github+json"}
            if GITHUB_TOKEN:
                hdr["Authorization"] = f"Bearer {GITHUB_TOKEN}"
            repo = _get_json(c, f"https://api.github.com/repos/{key}", hdr)
            release = None
            try:
                release = _get_json(c, f"https://api.github.com/repos/{key}/releases/latest", hdr)
            except Exception:
                pass                                   # no releases → no version_latest
            fields = fields_from_github(repo, release)
        elif source == "pypi":
            fields = fields_from_pypi(_get_json(c, f"https://pypi.org/pypi/{key}/json"))
        elif source == "npm":
            fields = fields_from_npm(_get_json(c, f"https://registry.npmjs.org/{key}"))
        elif source == "appstore":
            fields = fields_from_itunes(
                _get_json(c, f"https://itunes.apple.com/lookup?id={key}&entity=desktopSoftware"))
        elif source == "brew":
            sub, _, token = key.partition(":")
            if sub not in ("formula", "cask") or not token:
                return None
            fields = fields_from_brew(_get_json(c, f"https://formulae.brew.sh/api/{sub}/{token}.json"), sub)
        else:
            return None
        if not fields:
            return None
        image = fields.pop("image_url", None)
        return {"fields": fields, "image_url": image}
    except Exception:
        return None
    finally:
        if own:
            c.close()


# --- bookmarklet -------------------------------------------------------------------

# Same rules as inventory_clip._BOOKMARKLET_JS: statements only (lines are joined), single
# quotes only. A dumb harvester: the URL, the title, the Open Graph trio and the first
# SoftwareApplication / WebApplication / MobileApplication JSON-LD node, pruned to the
# scalar facts fields_from_payload reads. Routing to a registry happens server-side.
_SOFTWARE_JS = r"""
(function(){
var H='__HOST__',B='__BASE__/software/clip#';
if(location.host==H){alert('Drag me to your bookmarks bar, then click me on a repo, package, app store or pricing page.');return;}
function T(s){return (s==null?'':String(s)).replace(/\s+/g,' ').trim().slice(0,500);}
function m(p){var a=document.getElementsByTagName('meta');for(var k=0;k<a.length;k++){var e=a[k];if(e.getAttribute('property')==p||e.getAttribute('name')==p){var c=e.getAttribute('content');if(c)return T(c);}}return '';}
function nm(x){if(Array.isArray(x))x=x[0];return x?(typeof x=='string'?x:(x.name||'')):'';}
function im(x){if(!x)return '';if(Array.isArray(x))x=x[0];if(x&&typeof x=='object')x=x.url||x.contentUrl||'';return typeof x=='string'?x:'';}
var L=null,S=document.getElementsByTagName('script'),AT=['SoftwareApplication','WebApplication','MobileApplication'];
function walk(o){if(!o)return;if(Array.isArray(o)){o.forEach(walk);return;}if(typeof o!='object')return;if(o['@graph'])walk(o['@graph']);var t=o['@type'],ts=Array.isArray(t)?t:[t];if(!L&&ts.some(function(x){return AT.indexOf(x)>=0;}))L=o;}
for(var k=0;k<S.length;k++){if((S[k].getAttribute('type')||'')!='application/ld+json')continue;try{walk(JSON.parse(S[k].textContent));}catch(e){}}
var f=L&&L.offers;if(Array.isArray(f))f=f[0];
var A=L?{name:T(nm(L.name)),description:T(L.description),applicationCategory:T(nm(L.applicationCategory)),softwareVersion:T(L.softwareVersion),author:T(nm(L.author)),publisher:T(nm(L.publisher)),offers:(f&&typeof f=='object')?{price:T(f.price),priceCurrency:T(f.priceCurrency)}:null,image:T(im(L.image)||im(L.screenshot))}:null;
var P={url:location.href,domain:location.host,title:T(document.title),og_title:m('og:title'),og_description:m('og:description')||m('description'),og_image:m('og:image')||m('og:image:secure_url')||m('twitter:image'),ld_app:A};
var enc=btoa(unescape(encodeURIComponent(JSON.stringify(P)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
var w=window.open(B+enc,'money-clip-software','width=820,height=960');
if(!w)alert('Popup blocked - allow popups for this site and click again.');
})();
"""


def software_bookmarklet(base: str) -> str:
    """The software clipper's bookmark for the given app origin."""
    return build_bookmarklet(_SOFTWARE_JS, base)
