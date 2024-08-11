# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.search.sources.nx import nx_feed, nx_search


def get_search_results(shared_state, request_from, imdb_id=None):
    if imdb_id:
        results = nx_search(shared_state, request_from, imdb_id)
    else:
        results = nx_feed(shared_state, request_from)

    print(f"Providing {len(results)} releases from NX to {request_from}")
    return results
