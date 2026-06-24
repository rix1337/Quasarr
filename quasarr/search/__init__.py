# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timezone
from email.utils import parsedate_to_datetime
from threading import Lock

from quasarr.constants import (
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
)
from quasarr.providers.imdb_metadata import get_imdb_metadata
from quasarr.providers.log import (
    debug,
    get_source_logger,
    info,
    trace,
    warn,
)
from quasarr.search.sources import get_sources
from quasarr.search.sources.helpers.search_source import AbstractSearchSource
from quasarr.storage.categories import get_search_category_sources


def get_search_results(
    shared_state,
    request_from,
    search_category,
    imdb_id="",
    search_phrase="",
    season=None,
    episode=None,
    offset=0,
    limit=1000,
):
    from quasarr.providers.utils import (
        determine_search_category,
        get_base_search_category_id,
        get_search_behavior_category,
        get_search_cache_owner_category,
        get_search_capability_category,
        release_matches_search_category,
    )

    sources = get_sources()

    if imdb_id and not imdb_id.startswith("tt"):
        imdb_id = f"tt{imdb_id}"

    if imdb_id:
        get_imdb_metadata(imdb_id)

    episode_year = None
    episode_month = None
    episode_day = None
    if episode and "/" in str(episode):
        episode_date_raw = str(episode).split("/")
        if len(episode_date_raw) == 2:
            episode_year = season
            episode_month = episode_date_raw[0]
            episode_day = episode_date_raw[1]

    # Determine search category if not provided
    if not search_category:
        search_category = determine_search_category(request_from)

    # Resolve base category for logic (Movies, TV, etc.).
    base_search_category = (
        get_base_search_category_id(search_category) or search_category
    )
    behavior_search_category = (
        get_search_behavior_category(search_category) or search_category
    )
    capability_category = get_search_capability_category(search_category)
    is_custom_search_category = False
    try:
        is_custom_search_category = int(search_category) >= 100000
    except (TypeError, ValueError):
        pass
    # Cache keys are shared at the cache-family owner level.
    # Multi-category callers should execute same-family categories in ascending order
    # so the lowest category populates cache before stricter siblings run.
    cache_key_category = (
        search_category
        if is_custom_search_category
        else get_search_cache_owner_category(behavior_search_category)
    )

    # Filter out sources that are not in the search category's whitelist
    # We use the original search_category ID here to get the specific whitelist
    whitelisted_sources = get_search_category_sources(search_category)

    if whitelisted_sources:
        debug(
            f"Using whitelist for category <g>{search_category}</g>: {', '.join([s.upper() for s in whitelisted_sources])}"
        )

    start_time = time.time()
    search_executor = SearchExecutor()

    # Config retrieval
    config = shared_state.values["config"]("Hostnames")

    use_pagination = True

    # Use base_search_category for logic branching
    if imdb_id:
        stype = f"IMDb-ID <y>{imdb_id}</y>"

        if season:
            stype += f" <g>S{season}</g>"
        if episode:
            stype += f"{'' if season else ' '}<e>E{episode}</e>"
        if episode_year:
            stype += (
                f" <g>{episode_year}</g>-<e>{episode_month}</e>-<y>{episode_day}</y>"
            )

        if base_search_category in [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]:
            args = (shared_state, start_time, behavior_search_category)
            for source in sources.values():
                source_logger = get_source_logger(source.initials)

                if not config.get(source.initials):
                    source_logger.trace("Hostname missing in config")
                    continue

                if capability_category not in source.supported_categories:
                    source_logger.trace(
                        f"Category <g>{capability_category}</g> not supported"
                    )
                    continue

                if whitelisted_sources and source.initials not in whitelisted_sources:
                    source_logger.trace(
                        f"Category <g>{search_category}</g> not whitelisted"
                    )
                    continue

                if not source.supports_imdb:
                    source_logger.warn("IMDb ID unsupported")
                    continue

                if episode and not season and not source.supports_absolute_numbering:
                    source_logger.trace("Search with absolute EP number unsupported")
                    continue

                kwargs = {
                    "search_string": imdb_id,
                    "season": season,
                    "episode": episode,
                }

                if episode_year:
                    if not source.supports_date_numbering:
                        source_logger.trace("Search with date unsupported")
                        continue

                    kwargs.update(
                        {
                            "episode_year": episode_year,
                            "episode_month": episode_month,
                            "episode_day": episode_day,
                        }
                    )

                search_executor.add(
                    source,
                    args,
                    kwargs,
                    use_cache=True,
                    cache_category=cache_key_category,
                )
        else:
            warn(
                f"{stype} is not supported for <d>{request_from}</d>, category: {search_category} (Base: {base_search_category})"
            )

    elif search_phrase:
        stype = f"Search-Phrase <b>{search_phrase}</b>"
        if base_search_category in [SEARCH_CAT_BOOKS, SEARCH_CAT_MUSIC]:
            args = (shared_state, start_time, behavior_search_category)
            kwargs = {"search_string": search_phrase}
            for source in sources.values():
                source_logger = get_source_logger(source.initials)

                if not config.get(source.initials):
                    source_logger.trace("Hostname missing in config")
                    continue

                if capability_category not in source.supported_categories:
                    source_logger.trace(
                        f"Category <g>{capability_category}</g> not supported"
                    )
                    continue

                if whitelisted_sources and source.initials not in whitelisted_sources:
                    source_logger.trace(
                        f"Category <g>{search_category}</g> not whitelisted"
                    )
                    continue

                if not source.supports_phrase:
                    source_logger.warn("Search phrase unsupported")
                    continue

                search_executor.add(
                    source,
                    args,
                    kwargs,
                    use_cache=True,
                    cache_category=cache_key_category,
                )
        else:
            warn(
                f"{stype} is not supported for <d>{request_from}</d>, category: {search_category} (Base: {base_search_category})"
            )

    else:
        stype = "<b>Feed</b> search"
        args = (shared_state, start_time, behavior_search_category)
        kwargs = {}
        use_pagination = False
        for source in sources.values():
            source_logger = get_source_logger(source.initials)

            if not config.get(source.initials):
                source_logger.trace("Hostname missing in config")
                continue

            if capability_category not in source.supported_categories:
                source_logger.trace(
                    f"Category <g>{capability_category}</g> not supported"
                )
                continue

            if whitelisted_sources and source.initials not in whitelisted_sources:
                source_logger.trace(
                    f"Category <g>{search_category}</g> not whitelisted"
                )
                continue

            search_executor.add(
                source,
                args,
                kwargs,
                use_cache=True,
                ttl=60,
                action="feed",
                cache_category=cache_key_category,
            )

    debug(f"Starting <g>{len(search_executor.searches)}</g> searches for {stype}")

    # Unpack the new return values (all_cached, min_ttl)
    results, status_bar, all_cached, min_ttl = search_executor.run_all()

    elapsed_time = time.time() - start_time

    # Sort results by date (newest first)
    def get_date(item):
        try:
            dt = parsedate_to_datetime(item.get("details", {}).get("date", ""))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return parsedate_to_datetime("Thu, 01 Jan 1970 00:00:00 +0000")

    results.sort(key=get_date, reverse=True)

    filtered_results = [
        release
        for release in results
        if release_matches_search_category(
            search_category,
            release.get("details", {}).get("title", ""),
        )
    ]
    filtered_out_count = len(results) - len(filtered_results)
    if filtered_out_count > 0:
        debug(
            f"Filtered out <r>{filtered_out_count}</r> releases by title rules for category <g>{search_category}</g>"
        )
    results = filtered_results

    # Calculate pagination for logging and return
    total_count = len(results)

    # Slicing
    if use_pagination:
        sliced_results = results[offset : offset + limit]
    else:
        sliced_results = results

    if sliced_results:
        trace(f"First {len(sliced_results)} results sorted by date:")
        for i, res in enumerate(sliced_results):
            details = res.get("details", {})
            trace(f"{i + 1}. {details.get('date')} | {details.get('title')}")

    # Formatting for log (1-based index for humans)
    log_start = min(offset + 1, total_count) if total_count > 0 else 0
    log_end = min(offset + limit, total_count) if use_pagination else total_count

    # Logic to switch between "Time taken" and "from cache"
    if all_cached:
        time_info = f"from cache ({int(min_ttl)}s left)"
    else:
        time_info = f"Time taken: {elapsed_time:.2f} seconds"

    info(
        f"Providing releases <g>{log_start}-{log_end}</g> of <g>{total_count}</g> to <d>{request_from}</d> "
        f"for {stype}{status_bar} <blue>{time_info}</blue>"
    )

    return sliced_results


class SearchExecutor:
    def __init__(self):
        self.searches = []

    def add(
        self,
        source: AbstractSearchSource,
        args,
        kwargs,
        use_cache=False,
        ttl=300,
        action="search",
        cache_category=None,
    ):
        key_args = list(args)
        key_args[1] = None
        if cache_category is not None and len(key_args) >= 3:
            key_args[2] = cache_category
        key_args = tuple(key_args)
        key = hash((source.initials, action, key_args, frozenset(kwargs.items())))
        self.searches.append(
            (
                key,
                lambda: getattr(source, action)(*args, **kwargs),
                use_cache,
                ttl,
                source.initials,
            )
        )

    def run_all(self):
        results = []
        future_to_meta = {}

        # Track cache state
        all_cached = len(self.searches) > 0
        min_ttl = float("inf")
        bar_str = ""  # Initialize to prevent UnboundLocalError on full cache

        with ThreadPoolExecutor() as executor:
            current_index = 0
            pending_futures = []

            for key, func, use_cache, ttl, source_name in self.searches:
                cached_result = None
                exp = 0

                if use_cache:
                    # Get both result and expiry
                    cached_result, exp = search_cache.get(key)

                if cached_result is not None:
                    get_source_logger(source_name).debug(
                        f"Using cached result with cache_key '{key}'"
                    )
                    results.extend(cached_result)

                    # Calculate TTL for this cached item
                    ttl_left = exp - time.time()
                    if ttl_left < min_ttl:
                        min_ttl = ttl_left
                else:
                    all_cached = False
                    future = executor.submit(func)
                    cache_meta = (key, ttl) if use_cache else None
                    future_to_meta[future] = (current_index, cache_meta, source_name)
                    pending_futures.append(future)
                    current_index += 1

            if pending_futures:
                results_badges = [""] * len(pending_futures)

                for future in as_completed(pending_futures):
                    index, cache_meta, source_name = future_to_meta[future]
                    try:
                        res = future.result()
                        if res and len(res) > 0:
                            badge = f"<bg green><black>{source_name.upper()}</black></bg green>"
                        else:
                            get_source_logger(source_name).debug(
                                "❌ No results returned"
                            )
                            badge = f"<bg black><white>{source_name.upper()}</white></bg black>"

                        results_badges[index] = badge
                        results.extend(res)
                        if cache_meta:
                            cache_key, cache_ttl = cache_meta
                            search_cache.set(cache_key, res, ttl=cache_ttl)
                    except Exception as e:
                        results_badges[index] = (
                            f"<bg red><white>{source_name.upper()}</white></bg red>"
                        )
                        get_source_logger(source_name).warn(f"Search error: {e}")

                bar_str = f" [{' '.join(results_badges)}]"

        return results, bar_str, all_cached, min_ttl


class SearchCache:
    def __init__(self):
        self.last_cleaned = time.time()
        self.cache = {}
        self._lock = Lock()

    def clean(self, now):
        with self._lock:
            self._clean_locked(now)

    def _clean_locked(self, now):
        if now - self.last_cleaned < 60:
            return
        keys_to_delete = [k for k, (_, exp) in self.cache.items() if now >= exp]
        for k in keys_to_delete:
            del self.cache[k]
        self.last_cleaned = now

    def get(self, key):
        now = time.time()
        with self._lock:
            val, exp = self.cache.get(key, (None, 0))
            if now < exp:
                return (val, exp)

            # Clean up stale key opportunistically.
            if key in self.cache:
                del self.cache[key]
            return (None, 0)

    def set(self, key, value, ttl=300):
        now = time.time()
        with self._lock:
            self.cache[key] = (value, now + ttl)
            self._clean_locked(now)


search_cache = SearchCache()
