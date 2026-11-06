# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""SJ as a bundled template whose code steps live in the modules beside it.

SJ shares the Junkies login and protected links with its sibling site.
"""

TEMPLATE = {
    "name": "SJ",
    "language": "de",
    "categories": [5000, 5070],
    "urls": {
        "api_latest": "https://{host}/api/releases/latest/{days}",
        "series": "https://{host}/serie/{slug}",
        "series_search": "https://{host}/serie/search",
        "api_media_releases": "https://{host}/api/media/{media_id}/releases",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": False,
        "supports_absolute_numbering": False,
        "supports_date_numbering": True,
        "requires_login": True,
        "requires_account": True,
        "invite_only": False,
        "requires_flaresolverr": False,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
