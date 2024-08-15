# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.search.sources.fx import fx_feed, fx_search
from quasarr.search.sources.nx import nx_feed, nx_search


def get_search_results(shared_state, request_from, imdb_id=None):
    results = []
    if imdb_id:
        results.extend(nx_search(shared_state, request_from, imdb_id))
        results.extend(fx_search(shared_state, imdb_id))
    else:
        results.extend(nx_feed(shared_state, request_from))
        results.extend(fx_feed(shared_state))

    print(f"Providing {len(results)} releases to {request_from}")
    return results
