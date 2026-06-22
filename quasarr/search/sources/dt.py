# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import html
import re
import time
from datetime import timedelta, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, error, info, warn
from quasarr.providers.utils import (
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
    convert_to_mb,
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    is_valid_release,
    normalize_magazine_title,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "dt"
    language = "en"
    supports_imdb = True
    supports_phrase = True
    supported_categories = [
        SEARCH_CAT_MOVIES,
        SEARCH_CAT_SHOWS,
        SEARCH_CAT_MUSIC,
        SEARCH_CAT_BOOKS,
    ]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []
        dt = shared_state.values["config"]("Hostnames").get(self.initials)
        password = dt

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            feed_type = "learning/"
        elif base_search_category == SEARCH_CAT_MOVIES:
            feed_type = "media/videos/"
        elif base_search_category == SEARCH_CAT_SHOWS:
            feed_type = "media/tv-show/"
        elif base_search_category == SEARCH_CAT_MUSIC:
            feed_type = "media/music/"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        url = f"https://{dt}/{feed_type}"
        headers = {"User-Agent": shared_state.values["user_agent"]}

        try:
            r = requests.get(url, headers=headers, timeout=FEED_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            feed = BeautifulSoup(r.content, "html.parser")

            for article in feed.find_all("article"):
                try:
                    link_tag = article.select_one("h1.dt-flexible-title a")
                    if not link_tag:
                        # ad/promo articles lack a release title link; skip quietly
                        debug(f"Link tag not found in article: {article}")
                        continue

                    source = link_tag["href"]
                    title_raw = link_tag.text.strip()
                    title = (
                        title_raw.replace(" - ", "-")
                        .replace(" ", ".")
                        .replace("(", "")
                        .replace(")", "")
                    )

                    if base_search_category == SEARCH_CAT_BOOKS:
                        # magazarr can only detect specific date formats / issue numbering for magazines
                        title = normalize_magazine_title(title)

                    try:
                        imdb_id = re.search(r"tt\d+", str(article)).group()
                    except:
                        imdb_id = None

                    body_text = article.find("div", class_="dt-text-clamp").get_text(
                        " "
                    )
                    size_match = re.search(
                        r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB))", body_text, re.IGNORECASE
                    )
                    if not size_match:
                        debug(f"Size not found in article for {title_raw}")
                        continue
                    size_info = size_match.group(1).strip()
                    size_item = _extract_size(size_info)
                    mb = convert_to_mb(size_item)
                    size = mb * 1024 * 1024

                    published = _parse_published_datetime(article)

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
                    warn(f"Error parsing feed: {e}")
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
            error(f"Error loading feed: {e}")
            mark_hostname_issue(
                self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
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
        dt = shared_state.values["config"]("Hostnames").get(self.initials)
        password = dt

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            cat_id = "100"
        elif base_search_category == SEARCH_CAT_MOVIES:
            cat_id = "9"
        elif base_search_category == SEARCH_CAT_SHOWS:
            cat_id = "64"
        elif base_search_category == SEARCH_CAT_MUSIC:
            cat_id = "66"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        try:
            imdb_id = is_imdb_id(search_string)
            if imdb_id:
                search_string = get_localized_title(shared_state, imdb_id, "en")
                if not search_string:
                    info(f"Could not extract title from IMDb-ID {imdb_id}")
                    return releases
                search_string = html.unescape(search_string)

            q = quote_plus(search_string)

            url = (
                f"https://{dt}/index.php?"
                f"do=search&"
                f"subaction=search&"
                f"search_start=0&"
                f"full_search=1&"
                f"story={q}&"
                f"catlist%5B%5D={cat_id}&"
                f"sortby=date&"
                f"resorder=desc&"
                f"titleonly=3&"
                f"searchuser=&"
                f"beforeafter=after&"
                f"searchdate=0&"
                f"replyless=0&"
                f"replylimit=0&"
                f"showposts=0"
            )
            headers = {"User-Agent": shared_state.values["user_agent"]}

            r = requests.get(
                url,
                headers=headers,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            page = BeautifulSoup(r.content, "html.parser")

            for article in page.find_all("article"):
                try:
                    # search-result articles use h1.font-weight-bold, while
                    # the feed listing uses h1.dt-flexible-title
                    link_tag = article.select_one("h1.font-weight-bold a")
                    if not link_tag:
                        debug(f"No title link in search-article: {article}")
                        continue
                    source = link_tag["href"]
                    title_raw = link_tag.text.strip()
                    title = (
                        title_raw.replace(" - ", "-")
                        .replace(" ", ".")
                        .replace("(", "")
                        .replace(")", "")
                    )

                    if not is_valid_release(
                        title, search_category, search_string, season, episode
                    ):
                        continue

                    if base_search_category == SEARCH_CAT_BOOKS:
                        # magazarr can only detect specific date formats / issue numbering for magazines
                        title = normalize_magazine_title(title)

                    try:
                        imdb_id = re.search(r"tt\d+", str(article)).group()
                    except:
                        imdb_id = None

                    body_text = article.find("div", class_="dt-text-clamp").get_text(
                        " "
                    )
                    m = re.search(
                        r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB))", body_text, re.IGNORECASE
                    )
                    if not m:
                        debug(f"Size not found in search-article for {title_raw}")
                        continue
                    size_item = _extract_size(m.group(1).strip())
                    mb = convert_to_mb(size_item)
                    size = mb * 1024 * 1024

                    published = _parse_published_datetime(article)

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
                    warn(f"Error parsing search item: {e}")
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
            error(f"Error loading search page: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )

        elapsed = time.time() - start_time
        debug(f"Search time: {elapsed:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _extract_size(text):
    match = re.match(r"([\d\.]+)\s*([KMGT]B)", text, re.IGNORECASE)
    if match:
        size = match.group(1)
        unit = match.group(2).upper()
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def _parse_published_datetime(article):
    mon = article.select_one("small.dt-fs-11").text.strip()
    day = article.find("h4", class_="m-0").text.strip()
    year = article.find("h6", class_="m-0").text.strip()
    month_num = datetime.datetime.strptime(mon, "%b").month

    time_icon = article.select_one("i.bi-clock")
    if time_icon:
        # its parent <span> contains e.g. "19:12"
        raw = time_icon.parent.get_text(strip=True)
        m = re.search(r"(\d{1,2}:\d{2})", raw)
        if m:
            hh, mm = map(int, m.group(1).split(":"))
        else:
            hh, mm = 0, 0
    else:
        hh, mm = 0, 0

    # this timezone is fixed to CET+1 and might be wrong
    cet = timezone(timedelta(hours=1))
    dt = datetime.datetime(int(year), month_num, int(day), hh, mm, tzinfo=cet)
    return dt.isoformat()
