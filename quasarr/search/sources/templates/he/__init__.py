# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""HE as a bundled template whose steps are the site code beside it.

HE protects its links with its own CAPTCHA flow served by Quasarr.
"""

from quasarr.search.sources.templates.he import download as _download
from quasarr.search.sources.templates.he import search as _search

TEMPLATE = {
    "name": "HE",
    "language": "en",
    "categories": [2000, 5000, 5070],
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
    "hooks": {"feed": "run_feed", "search": "run_search", "download": "run_download"},
}


def run_feed(site, shared_state, start_time, search_category):
    return _search.Source().feed(shared_state, start_time, search_category)


def run_search(
    site,
    shared_state,
    start_time,
    search_category,
    search_string,
    season,
    episode,
    episode_date=None,
):
    return _search.Source().search(
        shared_state,
        start_time,
        search_category,
        search_string,
        season,
        episode,
        episode_date=episode_date,
    )


def run_download(site, shared_state, url, mirrors, title, password):
    return _download.Source().get_download_links(
        shared_state, url, mirrors, title, password
    )
