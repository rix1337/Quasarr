# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_ANIME,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
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
    initials = "he"
    language = "en"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS, SEARCH_CAT_SHOWS_ANIME]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        return self.search(shared_state, start_time, search_category)

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

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_MOVIES:
            tag = "movies"
        elif base_search_category == SEARCH_CAT_SHOWS:
            tag = "tv-shows"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        source_search = ""
        if search_string != "":
            imdb_id = is_imdb_id(search_string)
            if imdb_id:
                local_title = get_localized_title(shared_state, imdb_id, "en")
                if not local_title:
                    info(f"No title for IMDb {imdb_id}")
                    return releases
                if not season:
                    year = get_year(imdb_id)
                    if year:
                        local_title += f" {year}"
                source_search = local_title
            else:
                return releases
            source_search = unescape(source_search)
        else:
            imdb_id = None

        if not source_search:
            search_type = "feed"
            timeout = FEED_REQUEST_TIMEOUT_SECONDS
        else:
            search_type = "search"
            timeout = SEARCH_REQUEST_TIMEOUT_SECONDS

        if season:
            source_search += f" S{int(season):02d}"

            if episode:
                source_search += f"E{int(episode):02d}"

        url = f"https://{host}/tag/{tag}/"

        headers = {"User-Agent": shared_state.values["user_agent"]}
        params = {"s": source_search}

        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            results = soup.find_all("div", class_="item")
        except Exception as e:
            info(f"{search_type} load error: {e}")
            mark_hostname_issue(
                self.initials, search_type, str(e) if "e" in dir() else "Error occurred"
            )
            return releases

        if not results:
            return releases

        for result in results:
            try:
                data = result.find("div", class_="data")
                if not data:
                    continue

                headline = data.find("h5")
                if not headline:
                    continue

                a = headline.find("a", href=True)
                if not a:
                    continue

                source = a["href"].strip()

                head_title = a.get_text(strip=True)
                if not head_title:
                    continue

                head_split = head_title.split(" – ")
                title = head_split[0].strip()

                if not is_valid_release(
                    title, search_category, search_string, season, episode
                ):
                    trace("invalid release {}", title)
                    continue

                size_item = _extract_size(head_split[1].strip())
                mb = convert_to_mb(size_item)

                size = mb * 1024 * 1024

                published = ""
                post_time = data.find("span", class_="post-time")
                if post_time:
                    txt = post_time.get_text(" ", strip=True)
                    published = _parse_posted_ago(txt)
                    if published == "":
                        debug("missing publish date for {}", title)

                release_imdb_id = None
                try:
                    r = requests.get(
                        source,
                        headers=headers,
                        timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                    )
                    soup = BeautifulSoup(r.content, "html.parser")
                except Exception as e:
                    mark_hostname_issue(
                        self.initials,
                        search_type,
                        str(e) if "e" in dir() else "Error occurred",
                    )
                release_imdb_id = None
                try:
                    imdb_link = soup.find(
                        "a", href=re.compile(r"imdb\.com/title/tt\d+", re.IGNORECASE)
                    )
                    if imdb_link:
                        release_imdb_id = re.search(r"tt\d+", imdb_link["href"]).group()
                        if imdb_id and release_imdb_id and release_imdb_id != imdb_id:
                            trace(
                                f"IMDb ID mismatch: expected {imdb_id}, found {release_imdb_id}"
                            )
                            continue
                    else:
                        trace(f"imdb link not found for title {title}")
                except Exception:
                    debug(f"failed to determine imdb_id for title {title}")

                if release_imdb_id is None:
                    release_imdb_id = imdb_id

                password = None

                link = generate_download_link(
                    shared_state,
                    title,
                    source,
                    mb,
                    password,
                    release_imdb_id,
                    self.initials,
                )

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
            except Exception as e:
                debug(f"error parsing search result: {e}")
                continue

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")
        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _parse_posted_ago(txt):
    try:
        m = re.search(
            r"(\d+)\s*(sec|min|hour|day|week|month|year)s?", txt, re.IGNORECASE
        )
        if not m:
            return ""
        value = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("sec"):
            delta = timedelta(seconds=value)
        elif unit.startswith("min"):
            delta = timedelta(minutes=value)
        elif unit.startswith("hour"):
            delta = timedelta(hours=value)
        elif unit.startswith("day"):
            delta = timedelta(days=value)
        elif unit.startswith("week"):
            delta = timedelta(weeks=value)
        elif unit.startswith("month"):
            delta = timedelta(days=30 * value)
        else:
            delta = timedelta(days=365 * value)
        return (datetime.now(timezone.utc) - delta).strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )
    except Exception:
        return ""


def _extract_size(text: str) -> dict:
    match = re.search(
        r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*([A-Za-z]+)", text
    )
    if match:
        size = match.group(1).replace(",", "")
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}
    return {"size": "0", "sizeunit": "MB"}
