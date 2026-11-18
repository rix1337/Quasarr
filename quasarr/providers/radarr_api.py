# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import time

import requests

from quasarr.providers.log import trace, warn

_SHARED_STATE_KEY = "radarr_client"


def get_client(shared_state):
    """Return the cached Radarr client, or None when Radarr is not configured."""
    return shared_state.values.get(_SHARED_STATE_KEY)


def set_client(shared_state, client):
    """Store the Radarr client in shared state (pass None to clear)."""
    shared_state.update(_SHARED_STATE_KEY, client)


class RadarrAPIClient:
    """Minimal client for the Radarr v3 HTTP API.

    See https://radarr.video/docs/api/ for the full specification.
    """

    def __init__(self, base_url, api_key, timeout=10):
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _get(self, path, params=None, timeout=None):
        # A caller timeout only ever tightens the client's own: it says how much
        # of its budget is left, not that this request may take longer.
        timeout = min(self._timeout, timeout) if timeout else self._timeout
        url = f"{self._base_url}/api/v3{path}"
        headers = {
            "X-Api-Key": self._api_key,
            "Accept": "application/json",
        }
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            warn(f"Radarr API request to {url} failed: {e}")
            return None

    def movie_lookup_imdb(self, imdb_id):
        """Look up a movie on Radarr by its IMDb ID.

        Returns the parsed JSON movie object, or None when the request fails
        or Radarr cannot resolve the IMDb ID.
        """
        if not imdb_id:
            return None
        return self._get("/movie/lookup/imdb", params={"imdbId": imdb_id})

    def movie_lookup(self, term):
        """Return Radarr movie lookup candidates for a free-form title."""
        if not term:
            return []
        return self._get("/movie/lookup", params={"term": term}) or []

    def wanted(self, kind, page=1, page_size=50, timeout=None):
        """Return a wanted movies page (``kind`` is ``missing`` or ``cutoff``).

        ``None`` means the request failed. A caller walking pages must not read
        that as "no more pages".
        """
        return self._get(
            f"/wanted/{kind}",
            params={"page": page, "pageSize": page_size, "monitored": "true"},
            timeout=timeout,
        )


def get_tmdb_id(shared_state, imdb_id):
    """Return the tmdbId Radarr resolves for the given IMDb ID, or None."""
    client = get_client(shared_state)
    if client is None:
        warn("Radarr metadata lookup skipped: Radarr is not configured")
        return None

    movie = client.movie_lookup_imdb(imdb_id)
    if not movie:
        return None

    tmdb_id = movie.get("tmdbId")
    if not tmdb_id:
        warn(f"Radarr response for {imdb_id} did not include a TMDB ID")
        return None

    trace(f"Resolved IMDb ID '{imdb_id}' to TMDB ID '{tmdb_id}'")

    return tmdb_id


# Radarr statuses that mean the movie has at least reached cinemas; anything
# else (tba, announced) has no release to search for yet.
_RELEASED_STATUSES = {"inCinemas", "released"}


# Cap on wanted pages walked per kind so a library full of announced titles
# cannot turn one feed run into unbounded Radarr paging.
_WANTED_MAX_PAGES = 5


def get_wanted_imdb_ids(shared_state, limit=50, deadline=None, status=None):
    """Return IMDb IDs of monitored movies Radarr wants as a list.

    Covers both missing movies (no file) and cutoff-unmet ones (present but
    below the quality cutoff), missing first, capped at ``limit``, so a huge
    monitored library does not translate into a huge number of feed lookups.
    Movies not yet released to cinemas are skipped; pages are walked (bounded by
    ``_WANTED_MAX_PAGES``) so a wanted list front-loaded with announced titles
    still yields released ones instead of an empty seed. Empty when Radarr is
    not configured or the request fails.
    """
    if status is not None:
        # Callers that persist progress across runs need to know whether this is
        # the whole wanted list or as far as paging got.
        status["complete"] = False

    client = get_client(shared_state)
    if client is None:
        return []

    imdb_ids = []
    seen = set()
    for kind in ("missing", "cutoff"):
        for page in range(1, _WANTED_MAX_PAGES + 1):
            if len(imdb_ids) >= limit:
                return imdb_ids
            # Every page is its own Radarr request, so a slow instance must not
            # spend a caller's whole budget before it gets any seeds - and the
            # last page before the deadline must not overrun it either.
            page_timeout = None
            if deadline is not None:
                page_timeout = deadline - time.time()
                if page_timeout <= 0:
                    return imdb_ids
            page_data = client.wanted(
                kind, page=page, page_size=limit, timeout=page_timeout
            )
            if page_data is None:
                return imdb_ids  # request failed: what we have is partial
            records = page_data.get("records", [])
            if not records:
                break  # no more pages for this kind
            for movie in records:
                if movie.get("status") not in _RELEASED_STATUSES:
                    continue
                imdb_id = movie.get("imdbId")
                if not imdb_id or imdb_id in seen:
                    continue
                seen.add(imdb_id)
                imdb_ids.append(imdb_id)
                if len(imdb_ids) >= limit:
                    if status is not None:
                        status["complete"] = True
                    return imdb_ids

    if status is not None:
        status["complete"] = True
    return imdb_ids
