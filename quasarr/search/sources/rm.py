# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.downloads.sources.rm import (
    _bootstrap_session,
    _build_release_page_url,
    _convert_iso_to_rss_date,
    _fetch_productions_page,
    _fetch_releases_by_production_ids,
    _get_base_url,
    _is_movie_release,
    _search_productions,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, info, trace, warn
from quasarr.providers.utils import (
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    is_valid_release,
    normalize_optional_int,
    release_matches_search_category,
    search_string_in_sanitized_title,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource

_LEADING_TAG_REGEX = re.compile(r"^(?:\[[^\]]+\]\s*)+")


class Source(AbstractSearchSource):
    initials = "rm"
    language = "en"
    supports_imdb = True
    supports_phrase = True
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []

        if get_base_search_category_id(search_category) not in (
            SEARCH_CAT_MOVIES,
            SEARCH_CAT_SHOWS,
        ):
            return releases

        try:
            release_items = _load_feed_release_items(
                shared_state,
                search_category,
                max_production_pages=10,
                timeout=FEED_REQUEST_TIMEOUT_SECONDS,
            )
            releases = _build_search_results(
                shared_state,
                release_items,
                search_category,
                search_string="",
                imdb_id=None,
                is_feed=True,
            )
            releases = releases[:20]
        except Exception as e:
            warn(f"Error loading feed: {e}")
            mark_hostname_issue(
                self.initials,
                "feed",
                str(e) if "e" in dir() else "Error occurred",
            )

        elapsed_time = time.time() - start_time
        debug(f"Time taken: {elapsed_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
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
        releases = []
        match_search_string = search_string

        if not search_string:
            return releases

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            localized_title = get_localized_title(shared_state, imdb_id, "en")
            if not localized_title:
                info(f"Could not extract title from IMDb-ID {imdb_id}")
                return releases
            search_string = html.unescape(localized_title)
            match_search_string = search_string
            if get_base_search_category_id(search_category) == SEARCH_CAT_MOVIES and (
                year := get_year(imdb_id)
            ):
                search_string += f" {year}"

        try:
            release_items = []
            search_session, productions = _load_search_productions(
                shared_state,
                search_string,
                SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            if productions:
                release_items = _fetch_releases_by_production_ids(
                    shared_state,
                    [production.get("id") for production in productions],
                    SEARCH_REQUEST_TIMEOUT_SECONDS,
                    session=search_session,
                )

            releases = _build_search_results(
                shared_state,
                release_items,
                search_category,
                search_string=match_search_string,
                imdb_id=imdb_id,
                season=season,
                episode=episode,
            )
        except Exception as e:
            warn(f"Error loading search: {e}")
            mark_hostname_issue(
                self.initials,
                "search",
                str(e) if "e" in dir() else "Error occurred",
            )

        elapsed_time = time.time() - start_time
        debug(f"Time taken: {elapsed_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _load_feed_release_items(
    shared_state, search_category, max_production_pages, timeout
):
    session = _bootstrap_session(shared_state, timeout)
    production_ids = []
    base_search_category = get_base_search_category_id(search_category)

    for page in range(1, max_production_pages + 1):
        payload = _fetch_productions_page(
            shared_state,
            page,
            timeout,
            session=session,
        )
        productions = payload.get("productions") or []
        if not productions:
            break

        for production in productions:
            if not _matches_production_category(production, base_search_category):
                continue
            production_id = production.get("id")
            if production_id:
                production_ids.append(production_id)

    if not production_ids:
        return []

    return _fetch_releases_by_production_ids(
        shared_state,
        production_ids,
        timeout,
        session=session,
    )


def _build_search_variants(search_string):
    normalized = " ".join(str(search_string or "").split())
    if not normalized:
        return []

    normalized = re.sub(r"[^\w\s]+", " ", normalized)
    normalized = " ".join(normalized.split())
    words = normalized.split()
    variants = []

    def append_word_variants(parts):
        if not parts:
            return

        variants.append(" ".join(parts))

        if len(parts) > 3:
            variants.append(" ".join(parts[:2]))
            variants.append(" ".join(parts[-3:]))
        elif len(parts) == 3:
            variants.append(parts[0])
            variants.append(" ".join(parts[-2:]))
        elif len(parts) == 2:
            variants.append(parts[0])
            variants.append(parts[1])

    append_word_variants(words)

    if words and words[-1].isdigit() and len(words[-1]) == 4:
        append_word_variants(words[:-1])

    seen = set()
    ordered = []
    for variant in variants:
        cleaned = " ".join(variant.split()).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)

    return ordered


def _load_search_productions(shared_state, search_string, timeout):
    session = _bootstrap_session(shared_state, timeout)
    productions_by_id = {}

    for variant in _build_search_variants(search_string):
        try:
            productions = _search_productions(
                shared_state,
                variant,
                timeout,
                session=session,
            )
        except Exception as e:
            trace(f'RM production search failed for variant "{variant}": {e}')
            continue
        for production in productions:
            production_id = production.get("id")
            if production_id and production_id not in productions_by_id:
                productions_by_id[production_id] = production

    return session, list(productions_by_id.values())


def _matches_production_category(production, base_search_category):
    medium_slug = (
        str((production.get("medium") or {}).get("slug") or "").strip().lower()
    )
    if not medium_slug:
        return False

    if base_search_category == SEARCH_CAT_MOVIES:
        return medium_slug == "movie"

    if base_search_category == SEARCH_CAT_SHOWS:
        return medium_slug != "movie"

    return False


def _matches_release_category(search_category, release):
    base_search_category = get_base_search_category_id(search_category)
    is_movie_release = _is_movie_release(release)

    if base_search_category == SEARCH_CAT_MOVIES:
        return is_movie_release

    if base_search_category == SEARCH_CAT_SHOWS:
        return not is_movie_release

    return False


def _matches_requested_release(
    release,
    title,
    search_category,
    search_string,
    season=None,
    episode=None,
):
    base_search_category = get_base_search_category_id(search_category)
    if base_search_category != SEARCH_CAT_SHOWS:
        return is_valid_release(title, search_category, search_string, season, episode)

    release_season = normalize_optional_int(release.get("season"))
    release_episode = normalize_optional_int(release.get("episode"))
    requested_season = normalize_optional_int(season)
    requested_episode = normalize_optional_int(episode)
    if release_season is None and release_episode is None:
        return is_valid_release(title, search_category, search_string, season, episode)

    if not search_string_in_sanitized_title(search_string, title):
        return False

    if requested_season is not None:
        if release_season is None:
            return is_valid_release(
                title, search_category, search_string, season, episode
            )
        if release_season != requested_season:
            return False

    if requested_episode is not None:
        if release_episode is None:
            return is_valid_release(
                title, search_category, search_string, season, episode
            )
        if release_episode != requested_episode:
            return False

    return True


def _normalize_display_title(title):
    normalized = html.unescape(str(title or "").strip())
    normalized = _LEADING_TAG_REGEX.sub("", normalized)
    normalized = " ".join(normalized.split())
    return normalized.replace(" ", ".")


def _build_search_results(
    shared_state,
    release_items,
    search_category,
    search_string,
    imdb_id,
    season=None,
    episode=None,
    is_feed=False,
):
    base_url = _get_base_url(shared_state)
    releases = []
    seen_sources = set()

    for release in release_items:
        try:
            if not _matches_release_category(search_category, release):
                continue

            raw_title = html.unescape(str(release.get("title") or "").strip())
            if not raw_title:
                continue

            if not release_matches_search_category(search_category, raw_title):
                continue

            if not is_feed and not _matches_requested_release(
                release,
                raw_title,
                search_category,
                search_string,
                season,
                episode,
            ):
                continue

            title = _normalize_display_title(raw_title)

            slug = str(release.get("slug") or "").strip()
            if not slug:
                continue

            source = _build_release_page_url(base_url, slug)
            if source in seen_sources:
                continue
            seen_sources.add(source)

            size_bytes = int(release.get("size") or 0)
            size_mb = size_bytes / (1024 * 1024) if size_bytes else 0
            published = _convert_iso_to_rss_date(
                release.get("updated_at") or release.get("created_at")
            )
            release_imdb_id = imdb_id

            releases.append(
                {
                    "details": {
                        "title": title,
                        "hostname": Source.initials,
                        "imdb_id": release_imdb_id,
                        "link": generate_download_link(
                            shared_state,
                            title,
                            source,
                            size_mb,
                            "",
                            release_imdb_id,
                            Source.initials,
                        ),
                        "size": size_bytes,
                        "date": published,
                        "source": source,
                    },
                    "type": "protected",
                }
            )
        except Exception as e:
            warn(f"Error parsing release: {e}")
            continue

    return releases
