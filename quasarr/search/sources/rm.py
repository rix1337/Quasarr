# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    IMDB_REGEX,
    MOVIE_REGEX,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
    SEASON_EP_REGEX,
)
from quasarr.downloads.sources.rm import (
    _build_release_page_url,
    _get_base_url,
    _get_page,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, warn
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    is_valid_release,
    release_matches_search_category,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource

_LEADING_TAG_REGEX = re.compile(r"^(?:\[[^\]]+\]\s*)+")
_TRAILING_SIZE_REGEX = re.compile(r"\s*\(\s*\d+(?:\.\d+)?\s*[KMGT]B\s*\)\s*$", re.I)
_SIZE_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGT]B)", re.I)
_RELATIVE_TIME_REGEX = re.compile(
    r"(\d+)\s*(second|minute|hour|day|week|month|year)s?", re.I
)
_RELATIVE_UNIT_DAYS = {"week": 7, "month": 30, "year": 365}

# one result page lists 25 releases; a phrase search is ranked by relevance, so
# the first pages carry what was asked for
SEARCH_RESULT_PAGES = 3
SEARCH_PAGE_SIZE = 25


class Source(AbstractSearchSource):
    initials = "rm"
    language = "en"
    supports_imdb = True
    supports_phrase = True
    supports_date_numbering = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []

        base_category = get_base_search_category_id(search_category)
        if base_category not in (SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS):
            return releases

        try:
            items = _parse_feed(
                _get_page(shared_state, "/", FEED_REQUEST_TIMEOUT_SECONDS)
            )
            # single odd posts are skipped; only a feed without any release is broken
            if not items:
                raise ValueError("Unexpected page layout (no parsable releases)")
            clear_hostname_issue(self.initials)
            items = [
                item
                for item in items
                if _title_fits_category(base_category, item["title"])
            ]
            releases = _build_search_results(shared_state, items, search_category)
        except Exception as e:
            warn(f"Error loading feed: {e}")
            mark_hostname_issue(self.initials, "feed", str(e))

        debug(f"Time taken: {time.time() - start_time:.2f}s")

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

        if not search_string:
            return releases

        imdb_id = is_imdb_id(search_string)

        try:
            if imdb_id:
                items = _search_by_imdb(shared_state, imdb_id)
            else:
                items = _search_by_phrase(shared_state, search_string, season, episode)

            items = [
                item
                for item in items
                if release_matches_search_category(search_category, item["title"])
                and is_valid_release(
                    item["title"], search_category, search_string, season, episode
                )
            ]
            releases = _build_search_results(
                shared_state, items, search_category, imdb_id=imdb_id
            )
            if items:
                clear_hostname_issue(self.initials)
        except Exception as e:
            warn(f"Error loading search: {e}")
            mark_hostname_issue(self.initials, "search", str(e))

        debug(f"Time taken: {time.time() - start_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _require_layout(soup, selector):
    """Fail loudly on a mirror that does not serve the expected page layout.

    Without this a mirror with another markup would just look like an empty
    site instead of showing up as a hostname issue.
    """
    if not soup.select_one(selector):
        raise ValueError(f"Unexpected page layout (missing {selector})")
    return soup


def _title_fits_category(base_category, title):
    if base_category == SEARCH_CAT_MOVIES:
        return bool(MOVIE_REGEX.match(title))
    return bool(SEASON_EP_REGEX.search(title))


def _clean_title(raw_title):
    title = html.unescape(str(raw_title or ""))
    title = html.unescape(title)
    title = title.replace("&", " and ")
    title = _LEADING_TAG_REGEX.sub("", " ".join(title.split()))
    title = _TRAILING_SIZE_REGEX.sub("", title)
    title = re.sub(r"['\":\(\)\[\]]", "", title)
    title = title.strip().replace(" ", ".")
    title = re.sub(r"\.+", ".", title)
    return title.strip(".")


def _size_mb(text):
    match = _SIZE_REGEX.search(str(text or ""))
    if not match:
        return 0
    return convert_to_mb({"size": match.group(1), "sizeunit": match.group(2)})


def _rfc_date(moment):
    return moment.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _relative_date(text):
    """Turn a listing's "7 hours" / "2 years" age into an approximate date."""
    match = _RELATIVE_TIME_REGEX.search(str(text or "").replace("\xa0", " "))
    now = datetime.now(timezone.utc)
    if not match:
        return _rfc_date(now)

    unit = match.group(2).lower()
    amount = int(match.group(1))
    if unit in _RELATIVE_UNIT_DAYS:
        delta = timedelta(days=amount * _RELATIVE_UNIT_DAYS[unit])
    else:
        delta = timedelta(**{f"{unit}s": amount})
    return _rfc_date(now - delta)


def _feed_date(post):
    """Feed posts carry a calendar date ("11/02" + year) without a time."""
    month_day = post.select_one("div.bloglist-date p.month-day")
    year = post.select_one("div.bloglist-date p.year")
    try:
        month, day = (int(part) for part in month_day.get_text(strip=True).split("/"))
        return _rfc_date(
            datetime(int(year.get_text(strip=True)), month, day, tzinfo=timezone.utc)
        )
    except Exception:
        return _rfc_date(datetime.now(timezone.utc))


def _release_href(anchor):
    href = anchor.get("href", "") if anchor else ""
    return href if href.startswith("/release/") else None


def _parse_feed(soup):
    items = []
    for post in soup.select("div.blog-post"):
        try:
            anchor = post.select_one("h3 a")
            href = _release_href(anchor)
            if not href:
                continue

            size_match = re.search(
                r"FILE SIZE:\s*([\d.]+\s*[KMGT]B)", post.get_text(" ")
            )
            imdb_link = post.find("a", href=IMDB_REGEX)
            items.append(
                {
                    "title": _clean_title(anchor.get_text()),
                    "href": href,
                    "size_mb": _size_mb(size_match.group(1)) if size_match else 0,
                    "date": _feed_date(post),
                    "imdb_id": IMDB_REGEX.search(imdb_link["href"]).group(1)
                    if imdb_link
                    else None,
                }
            )
        except Exception as e:
            debug(f"Skipping unparsable feed post: {e}")
    return items


def _parse_production_page(soup):
    """A title page lists all of its releases (movies, season packs, episodes)."""
    items = []
    for entry in soup.select("ul.allrls:not(#archived) li"):
        if entry.select_one(".dead"):
            continue
        anchor = entry.find("a", href=True)
        href = _release_href(anchor)
        if not href:
            continue

        items.append(
            {
                "title": _clean_title(anchor.get_text()),
                "href": href,
                "size_mb": _size_mb(anchor.get_text()),
                "date": _relative_date(
                    entry.select_one(".DIS_time").get_text()
                    if entry.select_one(".DIS_time")
                    else ""
                ),
                "imdb_id": None,
            }
        )
    return items


def _result_anchors(soup):
    """Titles and releases of a search result page share one list markup."""
    return soup.select("div.list_items li a.title")


def _parse_release_results(soup):
    items = []
    for anchor in _result_anchors(soup):
        href = _release_href(anchor)
        if not href:
            continue

        raw_title = anchor.get_text()
        items.append(
            {
                "title": _clean_title(raw_title),
                "href": href,
                "size_mb": _size_mb(raw_title),
                # result lists carry no date; the release is at least current
                "date": _rfc_date(datetime.now(timezone.utc)),
                "imdb_id": None,
            }
        )
    return items


def _search_by_imdb(shared_state, imdb_id):
    soup = _require_layout(
        _get_page(shared_state, f"/search/{imdb_id}", SEARCH_REQUEST_TIMEOUT_SECONDS),
        "div.lists-list",
    )

    for anchor in _result_anchors(soup):
        href = anchor.get("href", "")
        if href and not href.startswith("/release/"):
            # the title page has every release of the production, not just the
            # handful the search page previews
            try:
                title_soup = _require_layout(
                    _get_page(shared_state, href, SEARCH_REQUEST_TIMEOUT_SECONDS),
                    "div.blog-details",
                )
                items = _parse_production_page(title_soup)
                if items:
                    return items
            except Exception as e:
                debug(f"Failed to fetch or parse production page {href}: {e}")
            break

    return _parse_release_results(soup)


def _build_phrase_query(search_string, season, episode):
    query = str(search_string).strip()
    if season is not None:
        query += f" S{int(season):02d}"
        if episode is not None:
            query += f"E{int(episode):02d}"
    return query


def _search_by_phrase(shared_state, search_string, season, episode):
    query = quote_plus(_build_phrase_query(search_string, season, episode))
    items = []

    for page in range(1, SEARCH_RESULT_PAGES + 1):
        path = f"/search/{query}/releases/query"
        if page > 1:
            path += f"/b/{page}"
        page_items = _parse_release_results(
            _require_layout(
                _get_page(shared_state, path, SEARCH_REQUEST_TIMEOUT_SECONDS),
                "div.lists-list",
            )
        )
        items.extend(page_items)
        if len(page_items) < SEARCH_PAGE_SIZE:
            break

    return items


def _build_search_results(shared_state, items, search_category, imdb_id=None):
    base_url = _get_base_url(shared_state)
    releases = []
    seen_sources = set()

    for item in items:
        try:
            title = item["title"]
            if not title:
                continue

            source = _build_release_page_url(base_url, item["href"].rsplit("/", 1)[-1])
            if source in seen_sources:
                continue
            seen_sources.add(source)

            size_mb = item["size_mb"]
            release_imdb_id = item["imdb_id"] or imdb_id

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
                        "size": size_mb * 1024 * 1024,
                        "date": item["date"],
                        "source": source,
                    },
                    "type": "protected",
                }
            )
        except Exception as e:
            warn(f"Error parsing release: {e}")
            continue

    return releases
