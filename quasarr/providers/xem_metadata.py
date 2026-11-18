# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from datetime import datetime, timedelta
from json import dumps, loads

import requests

from quasarr.providers import shared_state
from quasarr.providers.imdb_metadata import TitleCleaner
from quasarr.providers.log import debug, trace, warn
from quasarr.providers.utils import search_string_in_sanitized_title


def _get_db(table_name):
    """Lazy import to avoid circular dependency."""
    from quasarr.storage.sqlite_database import DataBase

    return DataBase(table_name)


_BASE_URL = "https://thexem.info"


def _fetch_all_names():
    """Fetch all names from TheXEM, cached for 24 hours."""
    db = _get_db("xem_all_names")
    now = datetime.now().timestamp()

    try:
        cached_data = db.retrieve("allnames")
        if cached_data:
            cached = loads(cached_data)
            if cached.get("ttl") and cached["ttl"] > now:
                return cached.get("data")
    except Exception as e:
        trace(f"Error retrieving XEM allNames from cache: {e}")

    try:
        response = requests.get(
            f"{_BASE_URL}/map/allNames",
            params={
                "origin": "tvdb",
                "defaultNames": 1,
                "seasonNumbers": 1,
            },
            headers={"User-Agent": shared_state.values["user_agent"]},
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("result") != "success":
            warn(f"TheXEM allNames returned non-success: {result.get('message', '')}")
            return None

        data = result.get("data")
        ttl = now + timedelta(hours=24).total_seconds()
        db.update_store("allnames", dumps({"data": data, "ttl": ttl}))

        return data
    except Exception as e:
        warn(f"TheXEM allNames fetch failed: {e}")
        return None


def _search_in_names(all_names, title):
    """Search for a title in the allNames data. Returns TVDB ID or None."""
    sanitized_title = TitleCleaner.sanitize(title)

    for tvdb_id, names_list in all_names.items():
        for entry in names_list:
            if isinstance(entry, str):
                name = entry
            elif isinstance(entry, dict):
                for name in entry.keys():
                    if search_string_in_sanitized_title(sanitized_title, name):
                        return tvdb_id
                continue
            else:
                continue

            if search_string_in_sanitized_title(sanitized_title, name):
                return tvdb_id

    return None


def _fetch_season_names(tvdb_id):
    """Fetch per-season names for a specific show from TheXEM, cached for 24 hours."""
    db = _get_db("xem_season_names")
    now = datetime.now().timestamp()

    try:
        cached_data = db.retrieve(tvdb_id)
        if cached_data:
            cached = loads(cached_data)
            if cached.get("ttl") and cached["ttl"] > now:
                return cached.get("data")
    except Exception as e:
        trace(f"Error retrieving XEM season names from cache for {tvdb_id}: {e}")

    try:
        response = requests.get(
            f"{_BASE_URL}/map/names",
            params={
                "origin": "tvdb",
                "id": tvdb_id,
                "defaultNames": 1,
                "language": "jp",
            },
            headers={"User-Agent": shared_state.values["user_agent"]},
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("result") != "success":
            warn(
                f"TheXEM names for {tvdb_id} returned non-success: {result.get('message', '')}"
            )
            return None

        data = result.get("data", {})
        ttl = now + timedelta(hours=24).total_seconds()
        db.update_store(tvdb_id, dumps({"data": data, "ttl": ttl}))

        return data
    except Exception as e:
        warn(f"TheXEM names fetch failed for {tvdb_id}: {e}")
        return None


def get_season_name(title, season, lang="jp"):
    """
    Get season-specific name for a title and season from TheXEM.

    Returns the season name if found, otherwise None.
    """
    xem_data = get_all_season_names(title)
    if not xem_data:
        debug("Could not find season names for <y>{}</y>", title)
        return None

    season_names = xem_data.get(str(season))
    season_name = None
    if season_names:
        # Try to find a name in the requested language
        for l in season_names:
            if l == lang:
                season_name = season_names[l][0]
                break

        # Fallback to any available name
        if not season_name:
            trace(f'No season name found in language "{lang}" for "{title} S{season}"')
            if season_names:
                season_name = list(season_names.values())[0][0]
                trace(f'Falling back to language "{l}" for "{title} S{season}"')

    if not season_name:
        debug(f'No season name found for "{title} S{season}"')
        season_name = xem_data.get("all")
        if season_name:
            debug(f'Falling back to series name for "{title}"')

    if season_name:
        season_name = TitleCleaner.sanitize(season_name)
        debug(f'"{title} S{season}" => "{season_name}"')

    return season_name


def get_all_season_names(title):
    """
    Search TheXEM for a title and return per-season names.
    """

    # 1. Fetch allNames and search
    all_names = _fetch_all_names()
    if not all_names:
        return None

    tvdb_id = _search_in_names(all_names, title)
    if not tvdb_id:
        return None

    # 3. Fetch per-season names from TheXEM
    names_data = _fetch_season_names(tvdb_id)
    if not names_data:
        return None

    return names_data
