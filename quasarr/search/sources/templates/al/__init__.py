# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""AL as a bundled template whose steps are the site code beside it.

AL needs a logged-in session, reads anime metadata and selects single
episodes from multi-episode releases.
"""

from quasarr.search.sources.templates.al import download as _download
from quasarr.search.sources.templates.al import search as _search

TEMPLATE = {
    "name": "AL",
    "language": "de",
    "categories": [2000, 5000, 5070],
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
