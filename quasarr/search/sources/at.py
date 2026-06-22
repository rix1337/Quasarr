# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_ANIME,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.downloads.sources.at import (
    _build_release_info_from_title,
    _extract_direct_links_from_anchors,
    _extract_season_hint_from_title,
    _extract_series_title_from_listing_entry,
    _extract_series_title_from_raw_title,
    _extract_subtitle_langs_from_links,
    _parse_listing_datetime,
    _resolve_title_context,
)
from quasarr.downloads.sources.helpers.anime_title import guess_release_title
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, info, trace, warn
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    match_in_title,
    search_string_in_sanitized_title,
)
from quasarr.providers.xem_metadata import get_season_name
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource

_SEASON_DASH_EP_REGEX = re.compile(
    r"\bS(?:eason)?\s*0*(\d{1,3})\s*-\s*0*(\d{1,4})(?:\s*[-+]\s*0*(\d{1,4}))?",
    re.I,
)
_SEASON_EP_REGEX = re.compile(
    r"\bS(?:eason)?\s*0*(\d{1,3})\s*[.\-_ ]?(?:E|EP|Episode)\s*0*(\d{1,4})(?:\s*[-+]\s*(?:E|EP|Episode)?\s*0*(\d{1,4}))?\b",
    re.I,
)
_ABSOLUTE_EP_REGEX = re.compile(
    r"\b(?:EP?|Episode)\s*0*(\d{1,4})(?:\s*[-+]\s*0*(\d{1,4}))?\b", re.I
)
_ABSOLUTE_RANGE_REGEX = re.compile(r"[\[(]0*(\d{1,4})\s*[-+]\s*0*(\d{1,4})[\])]", re.I)
_ABSOLUTE_DASH_REGEX = re.compile(
    r"\s-\s0*(\d{1,3})(?:\s*[-+]\s*0*(\d{1,3}))?(?=[\s[(]|$)", re.I
)
_PLAIN_EP_REGEX = re.compile(r"(?:\.|^)[eE](\d{1,4})(?:-(\d{1,4}))?(?=[\.-]|$)")
_SEASON_WORD_REGEX = re.compile(r"\b(?:Season|Staffel)\s*0*(\d{1,3})\b", re.I)
_SIZE_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", re.I)


class Source(AbstractSearchSource):
    initials = "at"
    language = "en"
    supports_imdb = True
    supports_phrase = True
    supports_absolute_numbering = True
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS, SEARCH_CAT_SHOWS_ANIME]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []
        host = shared_state.values["config"]("Hostnames").get(self.initials)
        if not host:
            return releases

        try:
            entries = _load_entries(
                shared_state,
                f"https://{host}/",
                f"https://{host}/?disp=attachments",
                FEED_REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as e:
            warn(f"Error loading feed: {e}")
            mark_hostname_issue(self.initials, "feed", str(e) or "Error occurred")
            return releases

        seen_sources = set()
        for entry in entries:
            title = entry["title"]
            if entry["source"] in seen_sources:
                continue
            if not _matches_category(title, search_category):
                continue

            seen_sources.add(entry["source"])
            releases.append(
                {
                    "details": {
                        "title": title,
                        "hostname": self.initials,
                        "imdb_id": None,
                        "link": generate_download_link(
                            shared_state,
                            title,
                            entry["source"],
                            entry["mb"],
                            "",
                            None,
                            self.initials,
                        ),
                        "size": entry["mb"] * 1024 * 1024,
                        "date": entry["published"],
                        "source": entry["source"],
                    },
                    "type": "protected",
                }
            )

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")

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
        host = shared_state.values["config"]("Hostnames").get(self.initials)
        if not host:
            return releases

        season = _normalize_search_number(season)
        episode = _normalize_search_number(episode)

        base_category = get_base_search_category_id(search_category)
        if base_category not in (
            SEARCH_CAT_MOVIES,
            SEARCH_CAT_SHOWS,
            SEARCH_CAT_SHOWS_ANIME,
        ):
            warn(f"Unknown search category: {search_category}")
            return releases

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            localized_title = get_localized_title(shared_state, imdb_id, "en")
            if not localized_title:
                info(f"Could not extract title from IMDb-ID {imdb_id}")
                return releases
            search_string = localized_title

        for variant in _build_search_variants(search_string, imdb_id, season, episode):
            try:
                query = quote_plus(variant["query"])
                entries = _load_entries(
                    shared_state,
                    f"https://{host}/search?q={query}",
                    f"https://{host}/search?q={query}&disp=attachments",
                    SEARCH_REQUEST_TIMEOUT_SECONDS,
                )
            except Exception as e:
                warn(f"Error loading search for {variant['query']}: {e}")
                mark_hostname_issue(self.initials, "search", str(e) or "Error occurred")
                continue

            seen_sources = set()
            for entry in entries:
                title = entry["title"]
                if entry["source"] in seen_sources:
                    continue
                if not _matches_entry_search(variant["match"], entry):
                    continue
                if not _matches_requested_release(
                    title,
                    search_category,
                    season=season,
                    episode=episode,
                    season_locked=variant["season_locked"],
                ):
                    continue

                seen_sources.add(entry["source"])
                releases.append(
                    {
                        "details": {
                            "title": title,
                            "hostname": self.initials,
                            "imdb_id": imdb_id,
                            "link": generate_download_link(
                                shared_state,
                                title,
                                entry["source"],
                                entry["mb"],
                                "",
                                imdb_id,
                                self.initials,
                            ),
                            "size": entry["mb"] * 1024 * 1024,
                            "date": entry["published"],
                            "source": entry["source"],
                        },
                        "type": "protected",
                    }
                )

            if releases:
                break

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _load_entries(shared_state, listing_url, attachments_url, request_timeout):
    headers = {"User-Agent": shared_state.values["user_agent"]}

    def fetch(url):
        response = requests.get(url, headers=headers, timeout=request_timeout)
        response.raise_for_status()
        return response.text

    responses = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(fetch, listing_url): "listing",
            executor.submit(fetch, attachments_url): "attachments",
        }
        for future in as_completed(futures):
            kind = futures[future]
            try:
                responses[kind] = future.result()
            except Exception:
                if kind == "listing":
                    raise
                responses[kind] = ""

    entries = _parse_listing_page(responses["listing"], listing_url)
    subtitle_langs_by_source = _parse_attachment_page(
        responses.get("attachments", ""), attachments_url
    )

    for entry in entries:
        entry["subtitle_langs"] = subtitle_langs_by_source.get(entry["source"], [])
        release_info = _build_release_info_from_title(
            entry["raw_title"], entry["subtitle_langs"]
        )
        entry["release_info"] = release_info

    season_hints_by_series = _build_season_hints(entries)

    for entry in entries:
        release_info = entry["release_info"]
        if release_info.season is None:
            season_hint = season_hints_by_series.get(_series_hint_key(entry))
            if season_hint is not None:
                release_info.season = season_hint

        page_title, release_info = _resolve_title_context(
            entry["series_title"]
            or _extract_series_title_from_raw_title(entry["raw_title"])
            or entry["raw_title"],
            entry["raw_title"],
            release_info,
        )
        entry["title"] = guess_release_title(page_title, release_info)

    return entries


def _parse_listing_page(html_text, page_url):
    entries = []
    soup = BeautifulSoup(html_text, "html.parser")

    for item in soup.select("div.home_list_entry"):
        title_link = item.select_one("div.link a[href]")
        links_div = item.select_one("div.links")
        size_node = item.select_one("div.size")
        if not title_link or not links_div:
            continue

        if not _extract_direct_links_from_anchors(links_div.find_all("a", href=True)):
            continue

        source = urljoin(page_url, title_link.get("href", "").strip())
        if not source:
            continue

        entries.append(
            {
                "raw_title": title_link.get_text(" ", strip=True),
                "series_title": _extract_series_title_from_listing_entry(item),
                "source": source,
                "published": _extract_listing_date(item),
                "mb": _extract_listing_size_mb(size_node),
                "subtitle_langs": [],
            }
        )

    return entries


def _parse_attachment_page(html_text, page_url):
    subtitle_langs_by_source = {}
    if not html_text:
        return subtitle_langs_by_source

    soup = BeautifulSoup(html_text, "html.parser")
    for entry in soup.select("div.home_list_entry"):
        title_link = entry.select_one("div.link a[href]")
        links_div = entry.select_one("div.links")
        if not title_link or not links_div:
            continue

        subtitle_langs = _extract_subtitle_langs_from_links(links_div)
        if subtitle_langs:
            subtitle_langs_by_source[urljoin(page_url, title_link["href"].strip())] = (
                subtitle_langs
            )

    return subtitle_langs_by_source


def _extract_listing_date(item):
    date_node = item.select_one("div.date[title]") or item.select_one(
        "div.date_icon[title]"
    )
    if not date_node:
        return ""

    return _parse_listing_datetime(date_node.get("title"))


def _extract_listing_size_mb(size_node):
    if not size_node:
        return 0

    match = _SIZE_REGEX.search(size_node.get_text(" ", strip=True))
    if not match:
        return 0

    return convert_to_mb({"size": match.group(1), "sizeunit": match.group(2).upper()})


def _build_search_variants(search_string, imdb_id, season, episode):
    variants = []
    season = _normalize_search_number(season)
    episode = _normalize_search_number(episode)

    def append_variants_for_query(query, match, season_locked):
        cleaned_query = str(query or "").strip()
        cleaned_match = str(match or "").strip()
        if not cleaned_query or not cleaned_match:
            return

        variants.append(
            {
                "query": cleaned_query,
                "match": cleaned_match,
                "season_locked": season_locked,
            }
        )

        if episode is None:
            return

        if season is not None:
            variants.append(
                {
                    "query": f"{cleaned_query} S{season:02d}E{episode:02d}",
                    "match": cleaned_match,
                    "season_locked": season_locked,
                }
            )

        variants.append(
            {
                "query": f"{cleaned_query} {episode}",
                "match": cleaned_match,
                "season_locked": season_locked,
            }
        )

    if season is not None:
        append_variants_for_query(
            f"{search_string} Season {season}",
            search_string,
            True,
        )

        xem_name = get_season_name(search_string, season, "en")
        if xem_name:
            append_variants_for_query(xem_name, xem_name, True)

    if imdb_id and season is None:
        year = get_year(imdb_id)
        if year:
            append_variants_for_query(
                f"{search_string} {year}",
                search_string,
                False,
            )

    append_variants_for_query(search_string, search_string, False)

    deduped_variants = []
    seen = set()
    for variant in variants:
        key = variant["query"].lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped_variants.append(variant)

    return deduped_variants


def _build_season_hints(entries):
    season_hints_by_series = {}

    for entry in entries:
        release_info = entry["release_info"]
        if release_info.season is None:
            explicit_hint = _extract_season_hint_from_title(
                entry["series_title"]
                or _extract_series_title_from_raw_title(entry["raw_title"])
            )
            if explicit_hint is not None:
                release_info.season = explicit_hint

        if release_info.season is None:
            continue

        key = _series_hint_key(entry)
        season_hints_by_series.setdefault(key, set()).add(release_info.season)

    return {
        key: next(iter(seasons))
        for key, seasons in season_hints_by_series.items()
        if len(seasons) == 1
    }


def _series_hint_key(entry):
    return (
        (
            entry["series_title"]
            or _extract_series_title_from_raw_title(entry["raw_title"])
        )
        .strip()
        .lower()
    )


def _matches_entry_search(search_string, entry):
    for candidate in [entry["title"], entry["raw_title"], entry["series_title"]]:
        if candidate and search_string_in_sanitized_title(search_string, candidate):
            return True

    trace(
        f"Search string '{search_string}' doesn't match '{entry['raw_title']}' or '{entry['title']}'"
    )
    return False


def _matches_category(title, search_category):
    base_category = get_base_search_category_id(search_category)

    if base_category == SEARCH_CAT_MOVIES:
        return not _looks_serial_release(title)

    if base_category in (SEARCH_CAT_SHOWS, SEARCH_CAT_SHOWS_ANIME):
        return _looks_serial_release(title)

    return False


def _matches_requested_release(title, search_category, season, episode, season_locked):
    season = _normalize_search_number(season)
    episode = _normalize_search_number(episode)

    if not _matches_category(title, search_category):
        return False

    if season is None and episode is None:
        return True

    if season is not None and episode is None:
        return _matches_season_pack(title, season)

    if match_in_title(title, season, episode):
        return True

    explicit_seasons = _extract_season_numbers(title)

    if season is not None:
        if _matches_season_dash_episode(title, season, episode):
            return True

        if explicit_seasons and season not in explicit_seasons:
            return False

        if season_locked:
            return _matches_absolute_episode(title, episode)

        return False

    if episode is not None:
        return _matches_absolute_episode(title, episode)

    return False


def _looks_serial_release(title):
    normalized_title = str(title or "")

    if match_in_title(normalized_title):
        return True
    if re.search(r"\bS\d{1,3}E\d{1,4}(?:-\d{1,4})?\b", normalized_title, re.I):
        return True
    if _SEASON_DASH_EP_REGEX.search(normalized_title):
        return True
    if _ABSOLUTE_EP_REGEX.search(normalized_title):
        return True
    if _ABSOLUTE_RANGE_REGEX.search(normalized_title):
        return True
    if _ABSOLUTE_DASH_REGEX.search(normalized_title):
        return True
    if _PLAIN_EP_REGEX.search(normalized_title):
        return True
    if _SEASON_WORD_REGEX.search(normalized_title):
        return True

    return False


def _matches_season_dash_episode(title, season, episode):
    for match in _SEASON_DASH_EP_REGEX.finditer(title):
        if int(match.group(1)) != int(season):
            continue

        if episode is None:
            return True

        start = int(match.group(2))
        end = int(match.group(3) or start)
        if start <= int(episode) <= end:
            return True

    return False


def _matches_absolute_episode(title, episode):
    episode = _normalize_search_number(episode)
    if episode is None:
        return False

    for start, end in _extract_absolute_ranges(title):
        if start <= episode <= end:
            return True

    return False


def _matches_season_pack(title, season):
    explicit_seasons = _extract_season_numbers(title)
    if explicit_seasons and season not in explicit_seasons:
        return False

    episode_ranges = _extract_episode_ranges(title, season)
    if any(start == end for start, end in episode_ranges):
        return False

    normalized_title = str(title or "")
    if explicit_seasons:
        return True

    if season == 1 and re.search(
        r"\b(?:batch|complete|全集|pack)\b", normalized_title, re.I
    ):
        return True

    return False


def _extract_absolute_ranges(title):
    ranges = []

    for pattern in (
        _ABSOLUTE_EP_REGEX,
        _ABSOLUTE_RANGE_REGEX,
        _ABSOLUTE_DASH_REGEX,
        _PLAIN_EP_REGEX,
    ):
        for match in pattern.finditer(title):
            start = int(match.group(1))
            if match.lastindex and match.lastindex >= 2 and match.group(2):
                end = int(match.group(2))
            else:
                end = start
            ranges.append((start, end))

    return ranges


def _extract_episode_ranges(title, season=None):
    ranges = []

    for match in _SEASON_EP_REGEX.finditer(title):
        match_season = int(match.group(1))
        if season is not None and match_season != int(season):
            continue

        start = int(match.group(2))
        end = int(match.group(3) or start)
        ranges.append((start, end))

    if season is None or int(season) == 1:
        ranges.extend(_extract_absolute_ranges(title))

    deduped_ranges = []
    seen = set()
    for start, end in ranges:
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        deduped_ranges.append(key)

    return deduped_ranges


def _extract_season_numbers(title):
    seasons = set()

    for match in re.finditer(r"\bS(\d{1,3})(?=E\d{1,4}\b|\b)", title, re.I):
        seasons.add(int(match.group(1)))

    for match in _SEASON_WORD_REGEX.finditer(title):
        seasons.add(int(match.group(1)))

    return seasons


def _normalize_search_number(value):
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None
