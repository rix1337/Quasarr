# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""WX as a bundled template whose code steps live in the modules beside it.

WX reads RSS for the feed and a JSON API for search and release details.
"""

TEMPLATE = {
    "name": "WX",
    "language": "de",
    "categories": [2000, 5000, 5070],
    # one Atom feed lists every kind of release
    "feeds": [
        {"category": 2000, "url": "https://{host}/rss"},
        {"category": 5000, "url": "https://{host}/rss"},
        {"category": 5070, "url": "https://{host}/rss"},
    ],
    "list": {
        "item": "entry, item",
        "title": {"selector": "title"},
        "link": [
            {"selector": 'link[rel="alternate"]', "attr": "href"},
            {"selector": "permalink"},
        ],
        "date": [{"selector": "updated"}, {"selector": "pubDate"}],
        "title_cleanup": "spaces",
        "dedupe": False,
        "find_imdb": False,
    },
    "download": {"password": "hostname_upper"},
    "urls": {
        "search_page": "https://{host}/search",
        "detail": "https://{host}/detail/{uid}",
        "api_search": "https://api.{host}/start/search",
        "api_detail": "https://api.{host}/start/d/{uid}",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": False,
        "supports_absolute_numbering": False,
        "supports_date_numbering": False,
        "requires_login": False,
        "requires_account": False,
        "invite_only": False,
        "requires_flaresolverr": False,
    },
    "hooks": {
        "search": "search",
        "download": "download",
        "package_identity": "download",
    },
}
