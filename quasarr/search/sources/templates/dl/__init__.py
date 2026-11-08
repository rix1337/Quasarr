# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""DL as a bundled template whose code steps live in the modules beside it.

DL is a logged-in forum: search pages through threads and pins posts by
fragment.
"""

TEMPLATE = {
    "name": "DL",
    "language": "de",
    "categories": [2000, 5000, 3000, 7000],
    "urls": {
        "forum_movies": "https://www.{host}/forums/hd.8/?order=post_date&direction=desc",
        "forum_shows": "https://www.{host}/forums/hd.14/?order=post_date&direction=desc",
        "forum_music": "https://www.{host}/forums/alben.42/?order=post_date&direction=desc",
        "forum_books": "https://www.{host}/forums/magazine-zeitschriften.72/?order=post_date&direction=desc",
        "search": "https://www.{host}/search/search",
        "search_results": "https://www.{host}/search/{search_id}/",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": True,
        "supports_absolute_numbering": False,
        "supports_date_numbering": True,
        "requires_login": True,
        "requires_account": True,
        "invite_only": False,
        "requires_flaresolverr": False,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
