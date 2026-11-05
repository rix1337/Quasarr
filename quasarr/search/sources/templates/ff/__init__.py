# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""FF as a bundled template whose code steps live in the modules beside it.

FF passes Cloudflare in a shared solver session and resolves link redirects.
"""

TEMPLATE = {
    "name": "FF",
    "language": "de",
    "categories": [2000, 2040, 2045],
    "urls": {
        "updates": "https://{host}/updates/{date}#list",
        "movie": "https://{host}/{movie_id}",
        "api_search": "https://{host}/api/v2/search?q={query}&ql=DE",
        "api_releases": "https://{host}/api/v1/{token}?filter=",
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
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
