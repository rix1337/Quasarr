# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""HE as a bundled template whose code steps live in the modules beside it.

HE protects its links with its own CAPTCHA flow served by Quasarr.
"""

TEMPLATE = {
    "name": "HE",
    "language": "en",
    "categories": [2000, 5000, 5070],
    "urls": {
        "listing_movies": "https://{host}/tag/movies/",
        "listing_shows": "https://{host}/tag/tv-shows/",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": False,
        "supports_absolute_numbering": False,
        "supports_date_numbering": True,
        "requires_login": False,
        "requires_account": False,
        "invite_only": False,
        "requires_flaresolverr": False,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
