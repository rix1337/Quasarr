# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""BY as a bundled template whose code steps live in the modules beside it.

Search follows result pages for date-numbered episodes and the feed has two
layouts; both stay as written.
"""

TEMPLATE = {
    "name": "BY",
    "language": "de",
    "categories": [7000, 2000, 5000, 3000],
    "urls": {
        "feed_movies": "https://{host}/?cat=1",
        "feed_shows": "https://{host}/?cat=2",
        "feed_music": "https://{host}/?cat=35",
        "feed_books": "https://{host}/?cat=71",
        "search": "https://{host}/?q={query}",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": True,
        "supports_absolute_numbering": False,
        "supports_date_numbering": True,
        "requires_login": False,
        "requires_account": False,
        "invite_only": False,
        "requires_flaresolverr": False,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
