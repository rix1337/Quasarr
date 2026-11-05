# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""RM as a bundled template whose steps are the site code beside it.

RM reads server-rendered pages with escaped markup, passes security checks
in one shared session and treats removed release pages specially.
"""

from quasarr.search.sources.templates.rm import download as _download
from quasarr.search.sources.templates.rm import search as _search

TEMPLATE = {
    "name": "RM",
    "language": "en",
    "categories": [2000, 5000],
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
        "feed": "run_feed",
        "search": "run_search",
        "download": "run_download",
        "package_identity": "run_package_identity",
    },
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


def run_package_identity(site, url):
    return _download.Source().get_package_identity(url)
