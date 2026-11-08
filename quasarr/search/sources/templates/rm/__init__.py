# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""RM as a bundled template whose code steps live in the modules beside it.

RM reads server-rendered pages with escaped markup, passes security checks
in one shared session and treats removed release pages specially.
"""

TEMPLATE = {
    "name": "RM",
    "language": "en",
    "categories": [2000, 5000],
    "urls": {
        "home": "https://{host}/",
        "search_imdb": "https://{host}/search/{imdb_id}",
        "search": "https://{host}/search/{query}/releases/query",
        "search_page": "https://{host}/search/{query}/releases/query/b/{page}",
        "release": "https://{host}/release/{slug}",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": True,
        "supports_absolute_numbering": False,
        "supports_date_numbering": False,
        "requires_login": False,
        "requires_account": False,
        "invite_only": False,
        "requires_flaresolverr": True,
    },
    "hooks": {
        "feed": "search",
        "search": "search",
        "download": "download",
        "package_identity": "download",
    },
}
