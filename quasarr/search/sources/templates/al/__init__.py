# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""AL as a bundled template whose code steps live in the modules beside it.

AL needs a logged-in session, reads anime metadata and selects single
episodes from multi-episode releases.
"""

TEMPLATE = {
    "name": "AL",
    "language": "de",
    "categories": [2000, 5000, 5070],
    "urls": {
        "home": "https://www.{host}/",
        "search": "https://www.{host}/search?q={query}",
        "captcha": "https://www.{host}/ajax/captcha",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": False,
        "supports_absolute_numbering": True,
        "supports_date_numbering": False,
        "requires_login": True,
        "requires_account": True,
        "invite_only": False,
        "requires_flaresolverr": True,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
