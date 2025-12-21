# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from quasarr.providers.log import info, debug
from quasarr.search.sources.al import al_feed, al_search
from quasarr.search.sources.by import by_feed, by_search
from quasarr.search.sources.dd import dd_search, dd_feed
from quasarr.search.sources.dj import dj_search, dj_feed
from quasarr.search.sources.dl import dl_search, dl_feed
from quasarr.search.sources.dt import dt_feed, dt_search
from quasarr.search.sources.dw import dw_feed, dw_search
from quasarr.search.sources.fx import fx_feed, fx_search
from quasarr.search.sources.he import he_feed, he_search
from quasarr.search.sources.mb import mb_feed, mb_search
from quasarr.search.sources.nk import nk_feed, nk_search
from quasarr.search.sources.nx import nx_feed, nx_search
from quasarr.search.sources.sf import sf_feed, sf_search
from quasarr.search.sources.sj import sj_search, sj_feed
from quasarr.search.sources.sl import sl_feed, sl_search
from quasarr.search.sources.wd import wd_feed, wd_search
from quasarr.search.sources.wx import wx_feed, wx_search


def get_search_results(shared_state, request_from, imdb_id="", search_phrase="", mirror=None, season="", episode=""):
    results = []

    if imdb_id and not imdb_id.startswith('tt'):
        imdb_id = f'tt{imdb_id}'

    docs_search = "lazylibrarian" in request_from.lower()

    al = shared_state.values["config"]("Hostnames").get("al")
    by = shared_state.values["config"]("Hostnames").get("by")
    dd = shared_state.values["config"]("Hostnames").get("dd")
    dl = shared_state.values["config"]("Hostnames").get("dl")
    dt = shared_state.values["config"]("Hostnames").get("dt")
    dj = shared_state.values["config"]("Hostnames").get("dj")
    dw = shared_state.values["config"]("Hostnames").get("dw")
    fx = shared_state.values["config"]("Hostnames").get("fx")
    he = shared_state.values["config"]("Hostnames").get("he")
    mb = shared_state.values["config"]("Hostnames").get("mb")
    nk = shared_state.values["config"]("Hostnames").get("nk")
    nx = shared_state.values["config"]("Hostnames").get("nx")
    sf = shared_state.values["config"]("Hostnames").get("sf")
    sj = shared_state.values["config"]("Hostnames").get("sj")
    sl = shared_state.values["config"]("Hostnames").get("sl")
    wd = shared_state.values["config"]("Hostnames").get("wd")
    wx = shared_state.values["config"]("Hostnames").get("wx")

    start_time = time.time()

    functions = []

    # Radarr/Sonarr use imdb_id for searches
    imdb_map = [
        (al, al_search),
        (by, by_search),
        (dd, dd_search),
        (dl, dl_search),
        (dt, dt_search),
        (dj, dj_search),
        (dw, dw_search),
        (fx, fx_search),
        (he, he_search),
        (mb, mb_search),
        (nk, nk_search),
        (nx, nx_search),
        (sf, sf_search),
        (sj, sj_search),
        (sl, sl_search),
        (wd, wd_search),
        (wx, wx_search),
    ]

    # LazyLibrarian uses search_phrase for searches
    phrase_map = [
        (by, by_search),
        (dl, dl_search),
        (dt, dt_search),
        (nx, nx_search),
        (sl, sl_search),
        (wd, wd_search),
    ]

    # Feed searches omit imdb_id and search_phrase
    feed_map = [
        (al, al_feed),
        (by, by_feed),
        (dd, dd_feed),
        (dj, dj_feed),
        (dl, dl_feed),
        (dt, dt_feed),
        (dw, dw_feed),
        (fx, fx_feed),
        (he, he_feed),
        (mb, mb_feed),
        (nk, nk_feed),
        (nx, nx_feed),
        (sf, sf_feed),
        (sj, sj_feed),
        (sl, sl_feed),
        (wd, wd_feed),
        (wx, wx_feed),
    ]

    if imdb_id:  # only Radarr/Sonarr are using imdb_id
        args, kwargs = (
            (shared_state, start_time, request_from, imdb_id),
            {'mirror': mirror, 'season': season, 'episode': episode}
        )
        for flag, func in imdb_map:
            if flag:
                functions.append(lambda f=func, a=args, kw=kwargs: f(*a, **kw))

    elif search_phrase and docs_search:  # only LazyLibrarian is allowed to use search_phrase
        args, kwargs = (
            (shared_state, start_time, request_from, search_phrase),
            {'mirror': mirror, 'season': season, 'episode': episode}
        )
        for flag, func in phrase_map:
            if flag:
                functions.append(lambda f=func, a=args, kw=kwargs: f(*a, **kw))

    elif search_phrase:
        debug(
            f"Search phrase '{search_phrase}' is not supported for {request_from}. Only LazyLibrarian can use search phrases.")

    else:
        args, kwargs = (
            (shared_state, start_time, request_from),
            {'mirror': mirror}
        )
        for flag, func in feed_map:
            if flag:
                functions.append(lambda f=func, a=args, kw=kwargs: f(*a, **kw))

    if imdb_id:
        stype = f'IMDb-ID "{imdb_id}"'
    elif search_phrase:
        stype = f'Search-Phrase "{search_phrase}"'
    else:
        stype = "feed search"

    info(f'Starting {len(functions)} search functions for {stype}... This may take some time.')

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(func) for func in functions]
        for future in as_completed(futures):
            try:
                result = future.result()
                results.extend(result)
            except Exception as e:
                info(f"An error occurred: {e}")

    elapsed_time = time.time() - start_time
    info(f"Providing {len(results)} releases to {request_from} for {stype}. Time taken: {elapsed_time:.2f} seconds")

    return results
