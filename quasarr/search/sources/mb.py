# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    CODEC_REGEX,
    FEED_REQUEST_TIMEOUT_SECONDS,
    IMDB_REGEX,
    MONTHS_MAP,
    RESOLUTION_REGEX,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
    XXX_REGEX,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, error, warn
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
    initials = "mb"
    language = "de"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]

    def _parse_posts(
        self,
        soup,
        shared_state,
        password,
        is_search=False,
        search_category=None,
        search_string=None,
        season=None,
        episode=None,
    ):
        releases = []
        one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        for post in soup.select("div.post"):
            try:
                # title & source
                h1 = post.find("h1")
                a = h1.find("a")
                source = a["href"].strip()
                title = a.get_text(strip=True)

                # parse date
                date_p = post.find("p", class_="date_x")
                date_txt = date_p.get_text(strip=True) if date_p else None
                published = one_hour_ago
                if date_txt:
                    m_date = re.search(
                        r"(?:\w+, )?(\d{1,2})\.\s*(\w+)\s+(\d{4})\s+(\d{2}:\d{2})",
                        date_txt,
                    )
                    if m_date:
                        day, mon_name, year, hm = m_date.groups()
                        mon = MONTHS_MAP.get(mon_name.lower(), "01")
                        dt_obj = datetime.strptime(
                            f"{day}.{mon}.{year} {hm}", "%d.%m.%Y %H:%M"
                        )
                        published = dt_obj.strftime("%a, %d %b %Y %H:%M:%S +0000")

                if is_search:
                    if not is_valid_release(
                        title, search_category, search_string, season, episode
                    ):
                        continue

                    # drop .XXX. unless user explicitly searched xxx
                    if XXX_REGEX.search(title) and "xxx" not in search_string.lower():
                        continue
                    # require resolution/codec
                    if not (
                        RESOLUTION_REGEX.search(title) or CODEC_REGEX.search(title)
                    ):
                        continue
                    # require no spaces in title
                    if " " in title:
                        continue

                # extract IMDb ID
                imdb_id = None
                for tag in post.find_all("a", href=True):
                    m = IMDB_REGEX.search(tag["href"])
                    if m:
                        imdb_id = m.group(1)
                        break

                if not imdb_id:
                    m = IMDB_REGEX.search(post.get_text())
                    if m:
                        imdb_id = m.group(1)

                # size extraction
                mb = size_bytes = 0
                size_match = re.search(
                    r"(?:Größe|Size).*?:\s*([\d\.]+)\s*([GMK]B)",
                    post.get_text(),
                    re.IGNORECASE,
                )
                if size_match:
                    sz = {"size": size_match.group(1), "sizeunit": size_match.group(2)}
                    mb = convert_to_mb(sz)
                    size_bytes = mb * 1024 * 1024

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
                error(f"Error parsing post: {e}")
                continue
        return releases

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        mb = shared_state.values["config"]("Hostnames").get(self.initials)

        base_search_category = get_base_search_category_id(search_category)

        password = mb
        if base_search_category == SEARCH_CAT_MOVIES:
            section = "neuerscheinungen"
        elif base_search_category == SEARCH_CAT_SHOWS:
            section = "serie"
        else:
            warn(f"Unknown search category: {search_category}")
            return []

        url = f"https://{mb}/category/{section}/"
        headers = {"User-Agent": shared_state.values["user_agent"]}
        try:
            r = requests.get(url, headers=headers, timeout=FEED_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            releases = self._parse_posts(soup, shared_state, password)
        except Exception as e:
            warn(f"Error loading feed: {e}")
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
        mb = shared_state.values["config"]("Hostnames").get(self.initials)

        password = mb
        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            search_string = imdb_id

        q = quote_plus(search_string)
        url = f"https://{mb}/?s={q}&id=20&post_type=post"
        headers = {"User-Agent": shared_state.values["user_agent"]}
        try:
            r = requests.get(
                url,
                headers=headers,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            releases = self._parse_posts(
                soup,
                shared_state,
                password,
                is_search=True,
                search_category=search_category,
                search_string=search_string,
                season=season,
                episode=episode,
            )
        except Exception as e:
            warn(f"Error loading search: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            releases = []
        debug(f"Time taken: {time.time() - start_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases
