# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.search.sources.dw import dw_feed, dw_search
from quasarr.search.sources.fx import fx_feed, fx_search
from quasarr.search.sources.nx import nx_feed, nx_search


def get_search_results(shared_state, request_from, imdb_id=None):
    results = []

    dw = shared_state.values["config"]("Hostnames").get("dw")
    fx = shared_state.values["config"]("Hostnames").get("fx")
    nx = shared_state.values["config"]("Hostnames").get("nx")

    if imdb_id:
        if dw:
            results.extend(dw_search(shared_state, request_from, imdb_id))
        if fx:
            results.extend(fx_search(shared_state, imdb_id))
        if nx:
            results.extend(nx_search(shared_state, request_from, imdb_id))
    else:
        if dw:
            results.extend(dw_feed(shared_state, request_from))
        if fx:
            results.extend(fx_feed(shared_state))
        if nx:
            results.extend(nx_feed(shared_state, request_from))

    print(f"Providing {len(results)} releases to {request_from}")
    return results
