# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""SF as a bundled template whose code steps live in the modules beside it.

SF passes Cloudflare in a shared solver session and selects episodes from packs.
"""

TEMPLATE = {
    "name": "SF",
    "language": "de",
    "categories": [5000, 5070],
    "urls": {
        "updates": "https://{host}/updates/{date}#list",
        "series": "https://{host}/{series_id}",
        "api_search": "https://{host}/api/v2/search?q={query}&ql=DE",
        "api_season": "https://{host}/api/v1/{season_id}/season/{season}?lang=ALL&_={epoch}",
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
