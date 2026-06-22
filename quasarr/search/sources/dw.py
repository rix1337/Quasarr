# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import re
import time

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    ENGLISH_MONTHS,
    FEED_REQUEST_TIMEOUT_SECONDS,
    GERMAN_MONTHS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info, trace, warn
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    is_valid_release,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "dw"
    language = "de"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []
        dw = shared_state.values["config"]("Hostnames").get(self.initials)
        password = dw

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_MOVIES:
            feed_type = "videos/filme/"
        elif base_search_category == SEARCH_CAT_SHOWS:
            feed_type = "videos/serien/"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        url = f"https://{dw}/{feed_type}"
        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        try:
            r = requests.get(url, headers=headers, timeout=FEED_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            feed = BeautifulSoup(r.content, "html.parser")
            articles = feed.find_all("h4")

            for article in articles:
                try:
                    source = article.a["href"]
                    title = article.a.text.strip()

                    try:
                        imdb_id = re.search(r"tt\d+", str(article)).group()
                    except:
                        imdb_id = None

                    size_info = article.find("span").text.strip()
                    size_item = _extract_size(size_info)
                    mb = convert_to_mb(size_item)
                    size = mb * 1024 * 1024
                    date = article.parent.parent.find(
                        "span", {"class": "date updated"}
                    ).text.strip()
                    published = _convert_to_rss_date(date)

                    link = generate_download_link(
                        shared_state,
                        title,
                        source,
                        mb,
                        password,
                        imdb_id,
                        self.initials,
                    )
                except Exception as e:
                    info(f"Error parsing feed: {e}")
                    mark_hostname_issue(
                        self.initials,
                        "feed",
                        str(e) if "e" in dir() else "Error occurred",
                    )
                    continue

                releases.append(
                    {
                        "details": {
                            "title": title,
                            "hostname": self.initials,
                            "imdb_id": imdb_id,
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": source,
                        },
                        "type": "protected",
                    }
                )

        except Exception as e:
            warn(f"Error loading feed: {e}")
            mark_hostname_issue(
                self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
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
        dw = shared_state.values["config"]("Hostnames").get(self.initials)
        password = dw

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_MOVIES:
            search_type = "videocategory=filme"
        elif base_search_category == SEARCH_CAT_SHOWS:
            search_type = "videocategory=serien"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        url = f"https://{dw}/?s={search_string}&{search_type}"
        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        try:
            r = requests.get(
                url,
                headers=headers,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            search = BeautifulSoup(r.content, "html.parser")
            results = search.find_all("h4")

        except Exception as e:
            warn(f"Error loading search feed: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            return releases

        imdb_id = is_imdb_id(search_string)

        if results:
            for result in results:
                try:
                    title = result.a.text.strip()

                    if not is_valid_release(
                        title, search_category, search_string, season, episode
                    ):
                        continue

                    try:
                        release_imdb_id = re.search(r"tt\d+", str(result)).group()
                    except:
                        release_imdb_id = None

                    if imdb_id and release_imdb_id and release_imdb_id != imdb_id:
                        trace(f"Skipping result '{title}' due to IMDb ID mismatch.")
                        continue

                    if release_imdb_id is None:
                        release_imdb_id = imdb_id

                    source = result.a["href"]
                    size_info = result.find("span").text.strip()
                    size_item = _extract_size(size_info)
                    mb = convert_to_mb(size_item)
                    size = mb * 1024 * 1024
                    date = result.parent.parent.find(
                        "span", {"class": "date updated"}
                    ).text.strip()
                    published = _convert_to_rss_date(date)

                    link = generate_download_link(
                        shared_state,
                        title,
                        source,
                        mb,
                        password,
                        release_imdb_id,
                        self.initials,
                    )
                except Exception as e:
                    warn(f"Error parsing search: {e}")
                    mark_hostname_issue(
                        self.initials,
                        "search",
                        str(e) if "e" in dir() else "Error occurred",
                    )
                    continue

                releases.append(
                    {
                        "details": {
                            "title": title,
                            "hostname": self.initials,
                            "imdb_id": release_imdb_id,
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": source,
                        },
                        "type": "protected",
                    }
                )

        elapsed_time = time.time() - start_time
        debug(f"Time taken: {elapsed_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _convert_to_rss_date(date_str):
    for german, english in zip(GERMAN_MONTHS, ENGLISH_MONTHS, strict=False):
        if german in date_str:
            date_str = date_str.replace(german, english)
            break

    parsed_date = datetime.datetime.strptime(date_str, "%d. %B %Y / %H:%M")
    rss_date = parsed_date.strftime("%a, %d %b %Y %H:%M:%S %z")

    return rss_date


def _extract_size(text):
    # First try the normal pattern: number + space + unit (e.g., "1024 MB")
    match = re.match(r"(\d+)\s+([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}

    # If that fails, try pattern with just unit (e.g., "MB")
    unit_match = re.match(r"([A-Za-z]+)", text.strip())
    if unit_match:
        unit = unit_match.group(1)
        # Fall back to 0 when size is missing
        return {"size": "0", "sizeunit": unit}

    # If neither pattern matches, raise the original error
    raise ValueError(f"Invalid size format: {text}")
