# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337
#
# MX — French DDL source.
# Original contribution by Riourik (https://github.com/riourik), PR #360.
#
# Flow (IMDb-driven):
#   1. IMDb ID -> localized title via get_localized_title(..., "fr")
#   2. search the title endpoint -> candidate entries (carry imdb_id + id)
#   3. match the entry whose imdb_id equals the requested IMDb ID
#   4. the download endpoint -> per-quality hoster links for that entry
#   5. the decode endpoint -> the real hoster URL
#
# The API returns the matching tmdb_id in its own search response and the
# download endpoint keys on the internal id alone, so no external
# TMDB/Radarr/Sonarr resolution is needed for searches. The feed has no native
# discovery endpoint, so it seeds from the *arr libraries.

import re
import time
from datetime import datetime, timezone

import requests

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import radarr_api, shared_state, sonarr_api
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, warn
from quasarr.providers.utils import (
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource

# Bound how many library items a single feed run queries, keeping RSS sync
# responsive on large libraries.
FEED_LIBRARY_LIMIT = 50


class Source(AbstractSearchSource):
    initials = "mx"
    language = "fr"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]
    # The movie feed reads Radarr and the show feed reads Sonarr (ID search
    # needs neither). Setup prompts remain source-wide, but feed() degrades
    # gracefully when only the unrelated client is missing.
    requires_radarr = True
    requires_sonarr = True

    # ------------------------------------------------------------------ #
    #  HTTP                                                               #
    # ------------------------------------------------------------------ #

    def _api(self, shared_state):
        """Return (api_base, host) from config, or (None, None) when unset."""
        host = shared_state.values["config"]("Hostnames").get(self.initials)
        if not host:
            return None, None
        return f"https://api.{host}/api", host

    def _get(self, api_base, host, path, params, shared_state, timeout):
        headers = {
            "User-Agent": shared_state.values["user_agent"],
            "Referer": f"https://{host}/",
            "Origin": f"https://{host}",
        }
        r = requests.get(
            f"{api_base}{path}", params=params, headers=headers, timeout=timeout
        )
        # The API answers 500 for content it does not index; treat as "no data"
        # rather than a hard error.
        if r.status_code == 500:
            return None
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ #
    #  Source API                                                         #
    # ------------------------------------------------------------------ #

    def _search(self, api_base, host, title, shared_state, timeout):
        data = self._get(
            api_base, host, "/search", {"title": title}, shared_state, timeout
        )
        return data.get("results", []) if data else []

    @staticmethod
    def _match_imdb(results, imdb_id):
        # The first result is not reliably the right one, so match explicitly on
        # the IMDb ID the API carries in each entry.
        for result in results:
            if result.get("imdb_id") == imdb_id:
                return result
        return None

    def _get_links(
        self,
        api_base,
        host,
        media_id,
        media_type,
        shared_state,
        timeout,
        season=None,
        episode=None,
    ):
        params = {}
        if media_type == "tv":
            params["season"] = season
            params["episode"] = episode
        data = self._get(
            api_base,
            host,
            f"/darkiworld/download/{media_type}/{media_id}",
            params,
            shared_state,
            timeout,
        )
        if data and data.get("success"):
            return data.get("all", [])
        return []

    def _decode_link(self, api_base, host, link_id, media_id, shared_state, timeout):
        # Some entries already expose a direct URL as their id.
        str_id = str(link_id)
        if str_id.startswith("http://") or str_id.startswith("https://"):
            return str_id

        data = self._get(
            api_base,
            host,
            f"/darkiworld/decode/{link_id}",
            {"title_id": media_id},
            shared_state,
            timeout,
        )
        if not data:
            return None
        embed_url = data.get("embed_url")
        if isinstance(embed_url, dict):
            # Object form (e.g. the Send hoster): real URL is under "lien".
            return (
                embed_url.get("lien") or embed_url.get("url") or embed_url.get("link")
            )
        if isinstance(embed_url, str) and embed_url:
            return embed_url
        return data.get("url") or data.get("link")

    # ------------------------------------------------------------------ #
    #  Release assembly                                                   #
    # ------------------------------------------------------------------ #

    def _build_releases(
        self,
        api_base,
        host,
        result,
        links,
        shared_state,
        timeout,
        season=None,
        episode=None,
    ):
        releases = []
        media_id = result.get("id")
        is_series = bool(result.get("is_series"))
        title = _sanitize(result.get("name", ""))
        year = (result.get("release_date") or "")[:4]
        imdb_id = result.get("imdb_id")

        for link in links:
            real_url = self._decode_link(
                api_base, host, link.get("id"), media_id, shared_state, timeout
            )
            if not real_url:
                debug(f"[mx] decode failed for link {link.get('id')}")
                continue

            quality = _normalize_quality(link.get("quality", ""))
            host_tag = _sanitize(link.get("host_name", ""))
            lang_tag = _sanitize(link.get("language", ""))
            size_bytes = link.get("size") or 0
            date = _to_rfc2822(link.get("upload_date", ""))

            if is_series:
                # season 0 (specials) is valid, so fall back / tag on None, not
                # on truthiness.
                saison = link.get("saison")
                if saison is None:
                    saison = season
                ep = link.get("episode")
                if ep is None:
                    ep = episode
                ep_tag = (
                    f"S{int(saison):02d}E{int(ep):02d}"
                    if saison is not None and ep is not None
                    else ""
                )
                parts = [title, ep_tag, quality, "MX", host_tag, lang_tag]
            else:
                parts = [title, year, quality, "MX", host_tag, lang_tag]
            release_title = ".".join(p for p in parts if p)

            link_payload = generate_download_link(
                shared_state,
                release_title,
                real_url,
                int(size_bytes / (1024 * 1024)) if size_bytes else 0,
                None,
                imdb_id,
                self.initials,
            )

            releases.append(
                {
                    "details": {
                        "title": release_title,
                        "hostname": self.initials,
                        "imdb_id": imdb_id,
                        "link": link_payload,
                        "size": size_bytes,
                        "date": date,
                        "source": f"https://{host}/",
                    },
                    "type": "protected",
                }
            )
        return releases

    def _releases_for_imdb(
        self,
        api_base,
        host,
        imdb_id,
        shared_state,
        timeout,
        season=None,
        episode=None,
    ):
        title = get_localized_title(shared_state, imdb_id, "fr")
        if not title:
            return []

        match = self._match_imdb(
            self._search(api_base, host, title, shared_state, timeout), imdb_id
        )
        if not match:
            return []

        media_type = "tv" if match.get("is_series") else "movie"
        if media_type == "tv" and (season is None or episode is None):
            # The API requires both season and episode for series downloads.
            return []

        links = self._get_links(
            api_base,
            host,
            match.get("id"),
            media_type,
            shared_state,
            timeout,
            season=season,
            episode=episode,
        )
        if not links:
            return []

        return self._build_releases(
            api_base,
            host,
            match,
            links,
            shared_state,
            timeout,
            season=season,
            episode=episode,
        )

    # ------------------------------------------------------------------ #
    #  Quasarr interface                                                  #
    # ------------------------------------------------------------------ #

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        api_base, host = self._api(shared_state)
        if not api_base:
            return []

        # No native "latest releases" endpoint exists, so the feed seeds from
        # the *arr libraries: monitored movies from Radarr, episodes from Sonarr.
        # The matching client must be configured; warn (don't fail) when it is
        # not, since the user may run a movie-only or TV-only setup.
        base_cat = get_base_search_category_id(search_category)
        if base_cat == SEARCH_CAT_MOVIES:
            if radarr_api.get_client(shared_state) is None:
                warn("[mx] movie feed needs Radarr configured — skipping")
                return []
            seeds = [
                (imdb_id, None, None)
                for imdb_id in radarr_api.get_wanted_imdb_ids(
                    shared_state, limit=FEED_LIBRARY_LIMIT
                )
            ]
        elif base_cat == SEARCH_CAT_SHOWS:
            if sonarr_api.get_client(shared_state) is None:
                warn("[mx] show feed needs Sonarr configured — skipping")
                return []
            seeds = [
                (ep["imdb_id"], ep["season"], ep["episode"])
                for ep in sonarr_api.get_wanted_episodes(
                    shared_state, limit=FEED_LIBRARY_LIMIT
                )
            ]
        else:
            return []

        releases = []
        failures = 0
        for imdb_id, season, episode in seeds[:FEED_LIBRARY_LIMIT]:
            try:
                releases.extend(
                    self._releases_for_imdb(
                        api_base,
                        host,
                        imdb_id,
                        shared_state,
                        FEED_REQUEST_TIMEOUT_SECONDS,
                        season=season,
                        episode=episode,
                    )
                )
            except Exception as e:
                failures += 1
                debug(f"[mx] feed item {imdb_id} error: {e}")

        if releases:
            clear_hostname_issue(self.initials)
        elif failures:
            # Seeds existed but every source lookup errored: surface the outage
            # instead of looking healthy with an empty feed. A feed that is just
            # empty (nothing wanted, or nothing available) is left untouched.
            mark_hostname_issue(
                self.initials, "feed", f"{failures} feed lookups failed"
            )
            warn(f"[mx] feed: all {failures} lookups failed")

        debug(f"[mx] feed: {len(releases)} releases — {time.time() - start_time:.2f}s")
        return releases

    def search(
        self,
        shared_state: shared_state,
        start_time: float,
        search_category: str,
        search_string: str = "",
        season: int = None,
        episode: int = None,
    ) -> list[SearchRelease]:
        api_base, host = self._api(shared_state)
        if not api_base:
            return []

        imdb_id = is_imdb_id(search_string)
        if not imdb_id:
            # MX matches strictly on IMDb ID; free-text queries are unsupported.
            return []

        releases = []
        try:
            releases = self._releases_for_imdb(
                api_base,
                host,
                imdb_id,
                shared_state,
                SEARCH_REQUEST_TIMEOUT_SECONDS,
                season=season,
                episode=episode,
            )
            if releases:
                clear_hostname_issue(self.initials)
        except Exception as e:
            mark_hostname_issue(self.initials, "search", str(e))
            warn(f"[mx] search error: {e}")

        debug(
            f"[mx] {len(releases)} releases for {imdb_id} — "
            f"{time.time() - start_time:.2f}s"
        )
        return releases


# ---------------------------------------------------------------------- #
#  Module helpers                                                         #
# ---------------------------------------------------------------------- #


def _sanitize(value):
    """Collapse whitespace and punctuation to dots for scene-style titles,
    preserving (accented) letters and digits."""
    return re.sub(r"[^\w]+", ".", value or "", flags=re.UNICODE).strip(".")


def _normalize_quality(quality):
    """Map source quality labels to scene-style resolution/source/codec tokens
    that Radarr/Sonarr recognize."""
    q = (quality or "").lower()

    if "2160" in q or "4k" in q or "uhd" in q or "ultra" in q:
        resolution = "2160p"
    elif "1080" in q:
        resolution = "1080p"
    elif "720" in q:
        resolution = "720p"
    else:
        resolution = ""

    if "remux" in q:
        source = "BluRay.REMUX"
    elif "blu" in q:
        source = "BluRay"
    elif "hdlight" in q:
        source = "WEBRip"
    elif "web" in q:
        source = "WEBDL"
    elif "hdtv" in q or "hdts" in q or "ts" in q or "cam" in q:
        source = "HDTV"
    else:
        source = ""

    if "x265" in q or "hevc" in q or "h265" in q:
        codec = "x265"
    elif "x264" in q or "h264" in q or "avc" in q:
        codec = "x264"
    else:
        codec = ""

    parts = [p for p in (resolution, source, codec) if p]
    # Fall back to the raw label only when nothing was recognized, so a codec is
    # never appended twice (e.g. "Ultra HD x265" -> "2160p.x265", not
    # "Ultra.HD.x265.x265").
    if not parts:
        return _sanitize(quality)
    return ".".join(parts)


def _to_rfc2822(date_str):
    try:
        dt = datetime.fromisoformat((date_str or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except Exception:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
