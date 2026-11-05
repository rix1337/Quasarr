# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""AT as a bundled template whose steps are the site code beside it.

AT lists anime releases with per-episode packs and resolves several hosters on
its own release pages.
"""

from quasarr.search.sources.templates.at import download as _download
from quasarr.search.sources.templates.at import search as _search

TEMPLATE = {
    "name": "AT",
    "language": "en",
    "categories": [2000, 5000, 5070],
    "capabilities": {
        "supports_imdb": True,
        "supports_phrase": True,
        "supports_absolute_numbering": True,
        "supports_date_numbering": False,
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
        shared_state, start_time, search_category, search_string, season, episode
    )


def run_download(site, shared_state, url, mirrors, title, password):
    return _download.Source().get_download_links(
        shared_state, url, mirrors, title, password
    )
