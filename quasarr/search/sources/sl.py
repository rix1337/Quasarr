# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import html
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_ANIME,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.cloudflare import ensure_session_cf_bypassed
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info, warn
from quasarr.providers.utils import (
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
    initials = "sl"
    language = "en"
    requires_flaresolverr = True
    supports_imdb = True
    supports_phrase = True
    supported_categories = [
        SEARCH_CAT_BOOKS,
        SEARCH_CAT_MOVIES,
        SEARCH_CAT_SHOWS,
        SEARCH_CAT_SHOWS_ANIME,
        SEARCH_CAT_MUSIC,
    ]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []

        sl = shared_state.values["config"]("Hostnames").get(self.initials)
        password = sl

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            feed_type = "ebooks"
        elif base_search_category == SEARCH_CAT_MOVIES:
            feed_type = "movies"
        elif base_search_category == SEARCH_CAT_SHOWS:
            feed_type = "tv-shows"
        elif base_search_category == SEARCH_CAT_MUSIC:
            feed_type = "music"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        url = f"https://{sl}/{feed_type}/feed/"
        headers = {"User-Agent": shared_state.values["user_agent"]}

        try:
            session = requests.Session()
            session, headers, r = ensure_session_cf_bypassed(
                info,
                shared_state,
                session,
                url,
                headers,
                timeout=FEED_REQUEST_TIMEOUT_SECONDS,
            )
            if not r:
                raise requests.RequestException("Cloudflare bypass failed")

            r.raise_for_status()
            root = ET.fromstring(r.text)

            for item in root.find("channel").findall("item"):
                try:
                    title = item.findtext("title").strip()
                    if base_search_category == SEARCH_CAT_BOOKS:
                        # magazarr can only detect specific date formats / issue numbering for magazines
                        title = normalize_magazine_title(title)

                    source = item.findtext("link").strip()

                    desc = item.findtext("description") or ""

                    size_match = re.search(
                        r"Size:\s*([\d\.]+\s*(?:GB|MB|KB|TB))", desc, re.IGNORECASE
                    )
                    if not size_match:
                        debug(f"Size not found in RSS item: {title}")
                        continue
                    size_info = size_match.group(1).strip()
                    size_item = _extract_size(size_info)
                    mb = convert_to_mb(size_item)
                    size = mb * 1024 * 1024

                    pubdate = item.findtext("pubDate").strip()
                    published = _parse_pubdate_to_iso(pubdate)

                    m = re.search(r"https?://www\.imdb\.com/title/(tt\d+)", desc)
                    imdb_id = m.group(1) if m else None

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
                                "size": size,
                                "date": published,
                                "source": source,
                            },
                            "type": "protected",
                        }
                    )

                except Exception as e:
                    warn(f"Error parsing feed item: {e}")
                    mark_hostname_issue(
                        self.initials,
                        "feed",
                        str(e) if "e" in dir() else "Error occurred",
                    )
                    continue

        except Exception as e:
            warn(f"Error loading feed: {e}")
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

        sl = shared_state.values["config"]("Hostnames").get(self.initials)
        password = sl

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            feed_type = "ebooks"
        elif base_search_category == SEARCH_CAT_MOVIES:
            feed_type = "movies"
        elif base_search_category == SEARCH_CAT_SHOWS:
            feed_type = "tv-shows"
        elif base_search_category == SEARCH_CAT_MUSIC:
            feed_type = "music"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        try:
            imdb_id = is_imdb_id(search_string)
            if imdb_id:
                search_string = get_localized_title(shared_state, imdb_id, "en") or ""
                search_string = html.unescape(search_string)
                if not search_string:
                    info(f"Could not extract title from IMDb-ID {imdb_id}")
                    return releases

            # Build the list of URLs to search. For tv-shows also search the "foreign" section.
            q = quote_plus(search_string)
            urls = [f"https://{sl}/{feed_type}/?s={q}"]
            if feed_type == "tv-shows":
                urls.append(f"https://{sl}/foreign/?s={q}")

            headers = {"User-Agent": shared_state.values["user_agent"]}

            # Fetch pages in parallel (so we don't double the slow site latency)
            def fetch(url):
                try:
                    debug(f"Fetching {url}")
                    session = requests.Session()
                    session, _, r = ensure_session_cf_bypassed(
                        info,
                        shared_state,
                        session,
                        url,
                        headers,
                        timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                    )
                    if not r:
                        raise requests.RequestException("Cloudflare bypass failed")
                    r.raise_for_status()
                    return r.text
                except Exception as e:
                    info(f"Error fetching url {url}: {e}")
                    mark_hostname_issue(
                        self.initials,
                        "search",
                        str(e) if "e" in dir() else "Error occurred",
                    )
                    return ""

            html_texts = []
            with ThreadPoolExecutor(max_workers=len(urls)) as tpe:
                futures = {tpe.submit(fetch, u): u for u in urls}
                for future in as_completed(futures):
                    try:
                        html_texts.append(future.result())
                    except Exception as e:
                        warn(f"Error fetching search page: {e}")
                        mark_hostname_issue(
                            self.initials,
                            "search",
                            str(e) if "e" in dir() else "Error occurred",
                        )

            # Parse each result and collect unique releases (dedupe by source link)
            seen_sources = set()
            for html_text in html_texts:
                if not html_text:
                    continue
                try:
                    soup = BeautifulSoup(html_text, "html.parser")
                    posts = soup.find_all(
                        "div", class_=lambda c: c and c.startswith("post-")
                    )

                    for post in posts:
                        try:
                            a = post.find("h1").find("a")
                            title = a.get_text(strip=True)

                            if not is_valid_release(
                                title, search_category, search_string, season, episode
                            ):
                                continue

                            if base_search_category == SEARCH_CAT_BOOKS:
                                title = normalize_magazine_title(title)
                                imdb_id = None

                            source = a["href"]
                            # dedupe
                            if source in seen_sources:
                                continue
                            seen_sources.add(source)

                            # Published date
                            time_tag = post.find("span", {"class": "localtime"})
                            published = None
                            if time_tag and time_tag.has_attr("data-lttime"):
                                published = time_tag["data-lttime"]
                            published = (
                                published
                                or datetime.datetime.utcnow().isoformat() + "+00:00"
                            )

                            size = 0

                            link = generate_download_link(
                                shared_state,
                                title,
                                source,
                                0,
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
                                        "size": size,
                                        "date": published,
                                        "source": source,
                                    },
                                    "type": "protected",
                                }
                            )
                        except Exception as e:
                            warn(f"Error parsing search item: {e}")
                            mark_hostname_issue(
                                self.initials,
                                "search",
                                str(e) if "e" in dir() else "Error occurred",
                            )
                            continue
                except Exception as e:
                    warn(f"Error parsing search HTML: {e}")
                    mark_hostname_issue(
                        self.initials,
                        "search",
                        str(e) if "e" in dir() else "Error occurred",
                    )
                    continue

        except Exception as e:
            warn(f"Error loading search page: {e}")
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


def _parse_pubdate_to_iso(pubdate_str):
    """
    Parse an RFC-822 pubDate from RSS into an ISO8601 string with timezone.
    """
    dt = datetime.datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %z")
    return dt.isoformat()
