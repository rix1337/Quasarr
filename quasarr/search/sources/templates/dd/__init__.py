# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""DD as a bundled template whose code steps live in the modules beside it.

DD needs a logged-in session and reads its API; the session lives in
quasarr.providers.sessions.
"""

TEMPLATE = {
    "name": "DD",
    "language": "en",
    "categories": [2000, 5000, 5070],
    "urls": {
        "home": "https://{host}/",
        "api_search": "https://{host}/api/releases/search",
    },
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": False,
        "supports_absolute_numbering": False,
        "supports_date_numbering": True,
        "requires_login": True,
        "requires_account": True,
        "invite_only": True,
        "requires_flaresolverr": False,
    },
    "hooks": {"feed": "search", "search": "search", "download": "download"},
}
