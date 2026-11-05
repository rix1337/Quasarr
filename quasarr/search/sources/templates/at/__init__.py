# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""AT as a bundled template whose code steps live in the modules beside it.

AT lists anime releases with per-episode packs and resolves several hosters on
its own release pages.
"""

TEMPLATE = {
    "name": "AT",
    "language": "en",
    "categories": [2000, 5000, 5070],
    "urls": {
        "feed": "https://{host}/",
        "feed_files": "https://{host}/?disp=attachments",
        "search": "https://{host}/search?q={query}",
        "search_files": "https://{host}/search?q={query}&disp=attachments",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": True,
        "supports_absolute_numbering": True,
        "supports_date_numbering": False,
        "requires_login": False,
        "requires_account": False,
        "invite_only": False,
        "requires_flaresolverr": False,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
