"""Clippers — the one page that hands out every bookmarklet the app has (Inventory,
Software), each bound to the app origin (BASE_URL or the request's). The old
per-board setup URL (/inventory/clip/setup, app/views/inventory_clip.py) redirects here so
existing bookmarks of the page keep working."""

from django.urls import path

from .. import web
from django.conf import settings
from ..inventory_clip import bookmarklet
from ..software_clip import software_bookmarklet


def clippers_for(base: str) -> list:
    return [
        {"key": "inventory", "label": "📎 Clip → Inventory", "href": bookmarklet(base),
         "heading": "Inventory", "board": "/inventory",
         "lede": "On a store product page: name, brand, price, model, color, size, dimensions and "
                 "images are collected, and the popup updates the Item whose Link matches the page "
                 "(per field, you tick what to apply) or adds a new one.",
         "notes": ["Amazon and IKEA have dedicated selectors (buy-box price, spec table, hi-res "
                   "gallery); other stores rely on their schema.org / Open Graph markup.",
                   "Images are downloaded by the server. If a store blocks that, the popup lets you "
                   "drag the image from the store tab instead."]},
        {"key": "software", "label": "💾 Clip → Software", "href": software_bookmarklet(base),
         "heading": "Software", "board": "/software",
         "lede": "On a GitHub repo, PyPI, npm, Mac App Store or Homebrew page the registry's own facts "
                 "are fetched (description, licence, latest version, stars, vendor, price); on any "
                 "other page the Open Graph and SoftwareApplication markup is used. The popup finds "
                 "the software by its source key or Link, or adds it as something you have.",
         "notes": ["Registry facts (latest version, stars, licence, repo) are stored read-only beside "
                   "the card; Status, Cost and Notes are yours.",
                   "Set GITHUB_TOKEN in .env to raise GitHub's anonymous 60 requests/hour."]},
    ]


@web.GET
def clippers_page(request):
    base = settings.BASE_URL or request.build_absolute_uri("/").rstrip("/")
    return web.page(request, "clippers.html", {"clippers": clippers_for(base)})


# The old per-board setup URL redirects here from app/views/inventory_clip.py.
urlpatterns = [
    path("clippers", clippers_page),
]
