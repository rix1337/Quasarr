# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""MX as a bundled template whose code steps live in the modules beside it.

MX reads a JSON API and matches releases by explicit IMDb identity.
"""

TEMPLATE = {
    "name": "MX",
    "language": "fr",
    "categories": [2000, 5000],
    "urls": {
        "api": "https://api.{host}/api",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": False,
        "supports_absolute_numbering": False,
        "supports_date_numbering": False,
        "requires_login": False,
        "requires_account": False,
        "invite_only": False,
        "requires_flaresolverr": True,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
