# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote, quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    CODEC_REGEX,
    FEED_REQUEST_TIMEOUT_SECONDS,
    RESOLUTION_REGEX,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
    XXX_REGEX,
)
from quasarr.providers import shared_state
from quasarr.providers.cloudflare import flaresolverr_get, is_cloudflare_challenge
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, error, info, warn
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    get_base_search_category_id,
    is_flaresolverr_available,
    is_imdb_id,
    is_valid_release,
    normalize_magazine_title,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "wd"
    language = "de"
    requires_flaresolverr = True
    supports_imdb = True
    supports_phrase = True
    supported_categories = [
        SEARCH_CAT_BOOKS,
        SEARCH_CAT_MOVIES,
        SEARCH_CAT_SHOWS,
        SEARCH_CAT_MUSIC,
    ]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        wd = shared_state.values["config"]("Hostnames").get(self.initials)
        password = wd

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            feed_type = "Ebooks"
        elif base_search_category == SEARCH_CAT_MOVIES:
            feed_type = "Movies"
        elif base_search_category == SEARCH_CAT_SHOWS:
            feed_type = "Serien"
        elif base_search_category == SEARCH_CAT_MUSIC:
            feed_type = "Music/Audio"
        else:
            warn(f"Unknown search category: {search_category}")
            return []

        url = f"https://{wd}/{feed_type}"
        headers = {"User-Agent": shared_state.values["user_agent"]}

        try:
            # Try normal request first
            try:
                r = requests.get(
                    url, headers=headers, timeout=FEED_REQUEST_TIMEOUT_SECONDS
                )
            except requests.RequestException:
                r = None

            # If blocked or failed, try FlareSolverr
            if r is None or r.status_code == 403 or is_cloudflare_challenge(r.text):
                if is_flaresolverr_available(shared_state):
                    debug("Encountered Cloudflare on feed. Trying FlareSolverr...")
                    r = flaresolverr_get(
                        shared_state,
                        url,
                        timeout=FEED_REQUEST_TIMEOUT_SECONDS,
                    )
                elif r is None:
                    raise requests.RequestException(
                        "Connection failed and FlareSolverr not available"
                    )
                elif r.status_code == 403 or is_cloudflare_challenge(r.text):
                    info(
                        "Cloudflare protection detected on feed but FlareSolverr is not configured."
                    )
                    mark_hostname_issue(
                        self.initials,
                        "feed",
                        "Cloudflare protection - FlareSolverr missing",
                    )
                    return []

            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            releases = self._parse_rows(soup, shared_state, wd, password)
        except Exception as e:
            error(f"Error loading feed: {e}")
            mark_hostname_issue(
                self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
            )
            releases = []
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
        wd = shared_state.values["config"]("Hostnames").get(self.initials)
        password = wd

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            search_string = get_localized_title(shared_state, imdb_id, "de")
            if not search_string:
                info(f"Could not extract title from IMDb-ID {imdb_id}")
                return releases
            search_string = html.unescape(search_string)
            if not season:
                if year := get_year(imdb_id):
                    search_string += f" {year}"

        q = quote_plus(search_string)
        url = f"https://{wd}/search?q={q}"
        headers = {"User-Agent": shared_state.values["user_agent"]}

        try:
            # Try normal request first
            try:
                r = requests.get(
                    url, headers=headers, timeout=SEARCH_REQUEST_TIMEOUT_SECONDS
                )
            except requests.RequestException:
                r = None

            # If blocked or failed, try FlareSolverr
            if r is None or r.status_code == 403 or is_cloudflare_challenge(r.text):
                if is_flaresolverr_available(shared_state):
                    debug("Encountered Cloudflare on search. Trying FlareSolverr...")
                    r = flaresolverr_get(
                        shared_state,
                        url,
                        timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                    )
                elif r is None:
                    raise requests.RequestException(
                        "Connection failed and FlareSolverr not available"
                    )
                elif r.status_code == 403 or is_cloudflare_challenge(r.text):
                    info(
                        "Cloudflare protection detected on search but FlareSolverr is not configured."
                    )
                    mark_hostname_issue(
                        self.initials,
                        "search",
                        "Cloudflare protection - FlareSolverr missing",
                    )
                    return []

            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            releases = self._parse_rows(
                soup,
                shared_state,
                wd,
                password,
                search_category=search_category,
                search_string=search_string,
                season=season,
                episode=episode,
                imdb_id=imdb_id,
            )
        except Exception as e:
            error(f"Error loading search: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            releases = []
        debug(f"Time taken: {time.time() - start_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases

    def _parse_rows(
        self,
        soup,
        shared_state,
        url_base,
        password,
        search_category=None,
        search_string=None,
        season=None,
        episode=None,
        imdb_id=None,
    ):
        """
        Walk the <table> rows, extract one release per row.

        Context detection:
        - feed when search_string is None
        - search when search_string is a str

        Porn-filtering:
        - feed: always drop .XXX.
        - search: drop .XXX. unless 'xxx' in search_string (case-insensitive)

        If in search context, also filter out non-video releases (ebooks, games).
        """
        releases = []
        is_search = search_string is not None

        base_search_category = get_base_search_category_id(search_category)

        one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        for tr in soup.select("table.table tbody tr.lh-sm"):
            try:
                a = tr.find("a", class_="upload-link")
                raw_href = a["href"]
                href = quote(raw_href, safe="/?:=&")
                source = f"https://{url_base}{href}"

                preview_div = a.find("div", class_="preview-text")
                date_txt = preview_div.get_text(strip=True) if preview_div else None
                if preview_div:
                    preview_div.extract()

                title = a.get_text(strip=True)

                # search context contains non-video releases (ebooks, games, etc.)
                if is_search:
                    if not is_valid_release(
                        title, search_category, search_string, season, episode
                    ):
                        continue

                    if base_search_category == SEARCH_CAT_BOOKS:
                        # magazarr can only detect specific date formats / issue numbering for magazines
                        title = normalize_magazine_title(title)
                    else:
                        # drop .XXX. unless user explicitly searched xxx
                        if (
                            XXX_REGEX.search(title)
                            and "xxx" not in search_string.lower()
                        ):
                            continue
                        # require resolution/codec
                        if not (
                            RESOLUTION_REGEX.search(title) or CODEC_REGEX.search(title)
                        ):
                            continue
                        # require no spaces in title
                        if " " in title:
                            continue

                size_txt = tr.find("span", class_="element-size").get_text(strip=True)
                sz = _extract_size(size_txt)
                mb = convert_to_mb(sz)
                size_bytes = mb * 1024 * 1024

                published = _convert_to_rss_date(date_txt) if date_txt else one_hour_ago

                link = generate_download_link(
                    shared_state,
                    title,
                    source,
                    mb,
                    password,
                    imdb_id,
                    self.initials,
                )

                releases.append(
                    {
                        "details": {
                            "title": title,
                            "hostname": self.initials,
                            "imdb_id": imdb_id,
                            "link": link,
                            "size": size_bytes,
                            "date": published,
                            "source": source,
                        },
                        "type": "protected",
                    }
                )
            except Exception as e:
                debug(f"Error parsing row: {e}")
                continue
        return releases


def _convert_to_rss_date(date_str):
    """
    date_str comes in as "02.05.2025 - 09:04"
    Return RFC‑822 style date with +0000 timezone.
    """
    parsed = datetime.strptime(date_str, "%d.%m.%Y - %H:%M")
    return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _extract_size(text):
    """
    e.g. "8 GB" → {"size": "8", "sizeunit": "GB"}
    """
    match = re.match(r"(\d+(?:\.\d+)?)\s*([A-Za-z]+)", text)
    if not match:
        raise ValueError(f"Invalid size format: {text!r}")
    return {"size": match.group(1), "sizeunit": match.group(2)}
