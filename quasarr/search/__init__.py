# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from concurrent.futures import ThreadPoolExecutor, as_completed

from quasarr.search.sources.dw import dw_feed, dw_search
from quasarr.search.sources.fx import fx_feed, fx_search
from quasarr.search.sources.nx import nx_feed, nx_search


def get_search_results(shared_state, request_from, search_string="", season="", episode=""):
    results = []

    dw = shared_state.values["config"]("Hostnames").get("dw")
    fx = shared_state.values["config"]("Hostnames").get("fx")
    nx = shared_state.values["config"]("Hostnames").get("nx")

    functions = []
    if search_string:
        if dw:
            functions.append(lambda: dw_search(shared_state, request_from, search_string))
        if fx:
            functions.append(lambda: fx_search(shared_state, search_string))
        if nx:
            functions.append(lambda: nx_search(shared_state, request_from, search_string))
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

    if search_string:
        print(f'Providing {len(results)} releases to {request_from} for search phrase "{search_string}"')
    else:
        print(f'Providing {len(results)} releases to {request_from} from release feed')

    return results
