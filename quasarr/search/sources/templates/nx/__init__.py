# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""NX as a bundled template whose code steps live in the modules beside it.

NX reads its JSON API and resolves links through a logged-in session.
"""

TEMPLATE = {
    "name": "NX",
    "language": "de",
    "categories": [7000, 2000, 5000, 3000],
    "urls": {
        "api_feed": "https://{host}/api/releases/by-date?page=1&limit=50&type={type}",
        "api_search": "https://{host}/api/search?q={query}&page=1",
        "release": "https://{host}/release/{slug}",
        "api_release": "https://{host}/api/releases/{slug}",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": True,
        "supports_absolute_numbering": False,
        "supports_date_numbering": False,
        "requires_login": False,
        "requires_account": True,
        "invite_only": False,
        "requires_flaresolverr": False,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
