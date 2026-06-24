# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from datetime import datetime, timedelta
from email.utils import format_datetime
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MOVIES_HD,
    SEARCH_CAT_MOVIES_UHD,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info, trace, warn
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    get_recently_searched,
    is_imdb_id,
    is_valid_release,
    sanitize_string,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "ff"
    language = "de"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [
        SEARCH_CAT_MOVIES,
        SEARCH_CAT_MOVIES_HD,
        SEARCH_CAT_MOVIES_UHD,
    ]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []
        host = shared_state.values["config"]("Hostnames").get(self.initials)
        password = host
        headers = {"User-Agent": shared_state.values["user_agent"]}

        date = datetime.now()
        days_to_cover = 2

        while days_to_cover > 0:
            days_to_cover -= 1
            if _feed_timed_out(start_time):
                debug("FF feed stopped before next date because timeout budget expired")
                break

            formatted_date = date.strftime("%Y-%m-%d")
            date -= timedelta(days=1)
            timeout = _remaining_feed_timeout(start_time)
            if timeout is None:
                break

            try:
                r = requests.get(
                    f"https://{host}/updates/{formatted_date}#list",
                    headers=headers,
                    timeout=timeout,
                )
                r.raise_for_status()
            except Exception as e:
                warn(f"Error loading feed: {e} for {formatted_date}")
                mark_hostname_issue(
                    self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
                )
                return releases

            content = BeautifulSoup(r.text, "html.parser")
            items = content.select("div.sra")

            for item in items:
                if _feed_timed_out(start_time):
                    debug("FF feed stopped during movie cross-reference")
                    break

                try:
                    movie_anchor = item.find("a", href=True, recursive=False)
                    if not movie_anchor:
                        continue
                    movie_path = movie_anchor["href"]
                    published = _parse_feed_date(formatted_date, item)

                    release_titles = {
                        a.get_text(strip=True): urljoin(f"https://{host}", a["href"])
                        for a in item.select("h2 > span > a[href]")
                        if a.get_text(strip=True)
                    }
                    if not release_titles:
                        continue

                    movie_data = _load_movie_data(
                        self,
                        shared_state,
                        host,
                        movie_path.strip("/"),
                        headers,
                        start_time=start_time,
                        feed=True,
                    )
                    if not movie_data:
                        continue

                    entries = {
                        entry["title"]: entry
                        for entry in movie_data["entries"]
                        if entry.get("title")
                    }
                    for title, source in release_titles.items():
                        entry = entries.get(title)
                        if not entry:
                            continue
                        mb = entry.get("mb", 0)
                        imdb_id = movie_data.get("imdb_id")
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
                                    "size": mb * 1024 * 1024,
                                    "date": published,
                                    "source": source,
                                },
                                "type": "protected",
                            }
                        )
                except Exception as e:
                    info(f"Error parsing feed: {e}")
                    mark_hostname_issue(
                        self.initials,
                        "feed",
                        str(e) if "e" in dir() else "Error occurred",
                    )

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
        episode_year: int = None,
        episode_month: int = None,
        episode_day: int = None,
    ) -> list[SearchRelease]:
        releases = []
        host = shared_state.values["config"]("Hostnames").get(self.initials)
        password = host

        imdb_id_in_search = is_imdb_id(search_string)
        if imdb_id_in_search:
            search_string = get_localized_title(shared_state, imdb_id_in_search, "de")
            if not search_string:
                info(f"Could not extract title from IMDb-ID {imdb_id_in_search}")
                return releases
            search_string = html.unescape(search_string)

        headers = {"User-Agent": shared_state.values["user_agent"]}
        url = f"https://{host}/api/v2/search?q={quote_plus(search_string)}&ql=DE"

        try:
            r = requests.get(
                url,
                headers=headers,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            feed = r.json()
        except Exception as e:
            warn(f"Error loading search: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            return releases

        for result in feed.get("result", []):
            sanitized_search_string = sanitize_string(search_string)
            sanitized_title = sanitize_string(result.get("title", ""))
            if not re.search(
                rf"\b{re.escape(sanitized_search_string)}\b", sanitized_title
            ):
                trace(
                    f"Search string '{search_string}' doesn't match '{result.get('title')}'"
                )
                continue

            movie_id = result.get("url_id")
            if not movie_id:
                continue

            movie_data = _load_movie_data(
                self,
                shared_state,
                host,
                movie_id,
                headers,
            )
            if not movie_data:
                continue

            imdb_id = movie_data.get("imdb_id")
            if imdb_id_in_search and imdb_id and imdb_id != imdb_id_in_search:
                trace(
                    f"Skipping result '{result.get('title')}' due to IMDb ID mismatch."
                )
                continue
            if imdb_id is None:
                imdb_id = imdb_id_in_search

            for entry in movie_data["entries"]:
                title = entry.get("title")
                if not title:
                    continue
                if not is_valid_release(title, search_category, search_string):
                    continue

                source = f"https://{host}/{movie_id}/{title}"
                mb = entry.get("mb", 0)
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
                            "size": mb * 1024 * 1024,
                            "date": (datetime.now() - timedelta(hours=1)).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "source": f"https://{host}/{movie_id}",
                        },
                        "type": "protected",
                    }
                )

        debug(f"Time taken: {time.time() - start_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _load_movie_data(
    source,
    shared_state,
    host,
    movie_id,
    headers,
    start_time=None,
    feed=False,
):
    context = "recents_ff"
    threshold = 60
    recently_searched = get_recently_searched(shared_state, context, threshold)
    entry = recently_searched.get(movie_id, {})
    ts = entry.get("timestamp")
    use_cache = ts and ts > datetime.now() - timedelta(seconds=threshold)
    if use_cache and entry.get("entries"):
        debug(f"Using cached content for '/{movie_id}'")
        return entry

    timeout = (
        _remaining_feed_timeout(start_time) if feed else SEARCH_REQUEST_TIMEOUT_SECONDS
    )
    if timeout is None:
        return None

    movie_url = f"https://{host}/{movie_id}"
    try:
        r = requests.get(movie_url, headers=headers, timeout=timeout)
        r.raise_for_status()
        movie_page = r.text
    except Exception as e:
        debug(f"Failed to load movie page for {movie_id}: {e}")
        mark_hostname_issue(source.initials, "feed" if feed else "search", str(e))
        return None

    content = BeautifulSoup(movie_page, "html.parser")
    imdb_link = content.find("a", href=re.compile(r"imdb\.com/title/tt\d+"))
    imdb_id = re.search(r"tt\d+", str(imdb_link)).group() if imdb_link else None
    token_match = re.search(r"initMovie\('([^']+)'", movie_page)
    if not token_match:
        mark_hostname_issue(
            source.initials, "feed" if feed else "search", "Missing movie token"
        )
        return None

    timeout = (
        _remaining_feed_timeout(start_time) if feed else SEARCH_REQUEST_TIMEOUT_SECONDS
    )
    if timeout is None:
        return None

    try:
        r = requests.get(
            f"https://{host}/api/v1/{token_match.group(1)}?filter=",
            headers=headers,
            timeout=timeout,
        )
        r.raise_for_status()
        data_html = r.json().get("html", "")
    except Exception as e:
        debug(f"Failed to load movie API for {movie_id}: {e}")
        mark_hostname_issue(source.initials, "feed" if feed else "search", str(e))
        return None

    movie_data = {
        "timestamp": datetime.now(),
        "imdb_id": imdb_id,
        "entries": _parse_entries(data_html),
    }
    recently_searched[movie_id] = movie_data
    shared_state.update(context, recently_searched)
    return movie_data


def _parse_entries(data_html):
    content = BeautifulSoup(data_html, "html.parser")
    entries = []
    for item in content.select("div.entry"):
        try:
            title = item.select_one("span.morespec").get_text(strip=True)
            size_text = _extract_labeled_text(item, "Größe:")
            mb = convert_to_mb(_extract_size(size_text)) if size_text else 0
            entries.append({"title": title, "mb": mb})
        except Exception as e:
            debug(f"Error parsing FF release entry: {e}")
    return entries


def _extract_labeled_text(entry, label):
    for item in entry.select("span.audiotag"):
        text = item.get_text(" ", strip=True)
        if text.startswith(label):
            return text.removeprefix(label).strip()
    return ""


def _extract_size(text):
    match = re.match(r"(\d+(\.\d+)?) ([A-Za-z]+)", text)
    if not match:
        raise ValueError(f"Invalid size format: {text}")
    return {"size": match.group(1), "sizeunit": match.group(3)}


def _parse_feed_date(formatted_date, item):
    published_time = item.select_one("span.timed").get_text(strip=True)
    parsed = datetime.strptime(f"{formatted_date} {published_time}", "%Y-%m-%d %H:%M")
    return format_datetime(parsed.astimezone())


def _feed_timed_out(start_time):
    return time.time() - start_time >= FEED_REQUEST_TIMEOUT_SECONDS


def _remaining_feed_timeout(start_time):
    if start_time is None:
        return FEED_REQUEST_TIMEOUT_SECONDS
    remaining = FEED_REQUEST_TIMEOUT_SECONDS - (time.time() - start_time)
    if remaining <= 0:
        return None
    return max(0.1, remaining)
