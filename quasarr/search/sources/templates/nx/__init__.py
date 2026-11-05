# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""NX as a bundled template whose steps are the site code beside it.

NX reads its JSON API and resolves links through a logged-in session.
"""

from quasarr.search.sources.templates.nx import download as _download
from quasarr.search.sources.templates.nx import search as _search

TEMPLATE = {
    "name": "NX",
    "language": "de",
    "categories": [7000, 2000, 5000, 3000],
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": True,
        "supports_absolute_numbering": False,
        "supports_date_numbering": False,
        "requires_login": False,
        "requires_account": True,
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
        shared_state, start_time, search_category, search_string, season, episode
    )


def run_download(site, shared_state, url, mirrors, title, password):
    return _download.Source().get_download_links(
        shared_state, url, mirrors, title, password
    )
