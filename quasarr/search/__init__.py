# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from concurrent.futures import ThreadPoolExecutor, as_completed

from quasarr.search.sources.dw import dw_feed, dw_search
from quasarr.search.sources.fx import fx_feed, fx_search
from quasarr.search.sources.nx import nx_feed, nx_search


def get_search_results(shared_state, request_from, imdb_id=None):
    results = []

    dw = shared_state.values["config"]("Hostnames").get("dw")
    fx = shared_state.values["config"]("Hostnames").get("fx")
    nx = shared_state.values["config"]("Hostnames").get("nx")

    functions = []
    if imdb_id:
        if dw:
            functions.append(lambda: dw_search(shared_state, request_from, imdb_id))
        if fx:
            functions.append(lambda: fx_search(shared_state, imdb_id))
        if nx:
            functions.append(lambda: nx_search(shared_state, request_from, imdb_id))
    else:
        if dw:
            functions.append(lambda: dw_feed(shared_state, request_from))
        if fx:
            functions.append(lambda: fx_feed(shared_state))
        if nx:
            functions.append(lambda: nx_feed(shared_state, request_from))

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(func) for func in functions]
        for future in as_completed(futures):
            try:
                result = future.result()
                results.extend(result)
            except Exception as e:
                print(f"An error occurred: {e}")

    print(f"Providing {len(results)} releases to {request_from}")
    return results
