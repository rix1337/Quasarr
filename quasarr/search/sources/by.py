# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from datetime import datetime
from urllib.parse import quote_plus

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
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, error, info, warn
from quasarr.providers.utils import (
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    is_valid_release,
    normalize_magazine_title,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "by"
    language = "de"
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
        by = shared_state.values["config"]("Hostnames").get(self.initials)
        password = by

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            feed_type = "?cat=71"
        elif base_search_category == SEARCH_CAT_MOVIES:
            feed_type = "?cat=1"
        elif base_search_category == SEARCH_CAT_SHOWS:
            feed_type = "?cat=2"
        elif base_search_category == SEARCH_CAT_MUSIC:
            feed_type = "?cat=35"
        else:
            warn(f"Invalid search category: {search_category}")
            return []

        base_url = f"https://{by}"
        url = f"{base_url}/{feed_type}"
        headers = {"User-Agent": shared_state.values["user_agent"]}
        try:
            r = requests.get(url, headers=headers, timeout=FEED_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            releases = self._parse_posts(
                soup,
                shared_state,
                base_url,
                password,
                search_category=search_category,
            )
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
        by = shared_state.values["config"]("Hostnames").get(self.initials)
        password = by

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            title = get_localized_title(shared_state, imdb_id, "de")
            if not title:
                info(f"Could not extract title from IMDb-ID {imdb_id}")
                return []
            search_string = html.unescape(title)
            if not season:
                if year := get_year(imdb_id):
                    search_string += f" {year}"

        base_url = f"https://{by}"
        q = quote_plus(search_string)
        url = f"{base_url}/?q={q}"
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
                base_url,
                password,
                is_search=True,
                search_category=search_category,
                search_string=search_string,
                season=season,
                episode=episode,
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

    def _parse_posts(
        self,
        soup,
        shared_state,
        base_url,
        password,
        is_search=False,
        search_category=None,
        search_string=None,
        season=None,
        episode=None,
    ):
        releases = []

        base_search_category = get_base_search_category_id(search_category)

        if not is_search:
            feed_container = soup.find(
                "table", class_="AUDIO_ITEMLIST"
            )  # it is actually called this way
            candidates = []
            if feed_container:
                for tbl in feed_container.find_all("table"):
                    if tbl.find(string=re.compile(r"Erstellt am:")):
                        candidates.append(tbl)

            # --- FALLBACK LOGIC ---
            # If the standard audio list logic found nothing, check the default list layout
            if not candidates:
                feed_container = soup.find("table", class_="DEFAULT_ITEMLIST")
                if feed_container:
                    # This layout uses TRs for items instead of nested Tables
                    # We filter by looking for the "TITLE" paragraph class unique to content rows
                    for tr in feed_container.find_all("tr"):
                        if tr.find("p", class_="TITLE"):
                            candidates.append(tr)

            items = candidates
        else:
            search_table = soup.find("table", class_="SEARCH_ITEMLIST")
            items = []
            if search_table:
                items = [
                    tr
                    for tr in search_table.find_all("tr")
                    if tr.find("p", class_="TITLE")
                    and tr.find("p", class_="TITLE").find("a", href=True)
                ]

        for entry in items:
            if entry.find("table"):
                continue  # Skip header rows
            try:
                if not is_search:
                    table = entry
                    # title & source
                    try:
                        link_tag = table.find("th").find("a")
                    except AttributeError:
                        link_tag = table.find("a")
                    title = link_tag.get_text(strip=True)
                    if not title:
                        try:
                            title = link_tag.get("title", "")
                        except:
                            pass
                    if not title:
                        continue
                    if base_search_category == SEARCH_CAT_BOOKS:
                        # magazarr can only detect specific date formats / issue numbering for magazines
                        title = normalize_magazine_title(title)
                    else:
                        title = title.replace(" ", ".")

                    source = base_url + link_tag["href"]
                    # extract date and size
                    date_str = size_str = None
                    for row in table.find_all("tr", height=True):
                        cols = row.find_all("td")
                        if len(cols) == 2:
                            label = cols[0].get_text(strip=True)
                            val = cols[1].get_text(strip=True)
                            if label.startswith("Erstellt am"):
                                date_str = val
                            elif label.startswith("Größe"):
                                size_str = val

                    if not date_str:
                        cols = entry.find_all("td")
                        if len(cols) >= 2:
                            val = cols[1].get_text(strip=True)
                            if re.match(r"\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}", val):
                                date_str = val

                    if not size_str:
                        cols = entry.find_all("td")
                        for col in cols:
                            val = col.get_text(strip=True)
                            if re.match(r"\d+(?:[.,]\d+)?\s*[A-Za-z]+", val):
                                size_str = val
                                break

                    published = _convert_to_rss_date(date_str) if date_str else ""
                    if not published:
                        debug("fuck")
                    size_info = (
                        _extract_size(size_str)
                        if size_str
                        else {"size": "0", "sizeunit": "MB"}
                    )
                    mb = float(size_info["size"])
                    size_bytes = int(mb * 1024 * 1024)
                    imdb_id = None
                else:
                    row = entry
                    title_tag = row.find("p", class_="TITLE").find("a")
                    title = title_tag.get_text(strip=True)
                    if base_search_category == SEARCH_CAT_BOOKS:
                        # magazarr can only detect specific date formats / issue numbering for magazines
                        title = normalize_magazine_title(title)
                    else:
                        title = title.replace(" ", ".")
                        if not (
                            RESOLUTION_REGEX.search(title) or CODEC_REGEX.search(title)
                        ):
                            continue

                    if not is_valid_release(
                        title, search_category, search_string, season, episode
                    ):
                        continue
                    if XXX_REGEX.search(title) and "xxx" not in search_string.lower():
                        continue

                    source = base_url + title_tag["href"]
                    date_cell = row.find_all("td")[2]
                    date_str = date_cell.get_text(strip=True)
                    if not re.match(r"\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}", date_str):
                        cols = row.find_all("td")
                        if len(cols) >= 2:
                            val = cols[1].get_text(strip=True)
                            if re.match(r"\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}", val):
                                date_str = val
                    published = _convert_to_rss_date(date_str)
                    size_bytes = 0
                    mb = 0
                    imdb_id = None

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
                debug(f"Error parsing: {e}")
                continue

        return releases


def _convert_to_rss_date(date_str):
    """
    BY date format: 'dd.mm.yy HH:MM', e.g. '20.07.25 17:48'
    """
    try:
        dt_obj = datetime.strptime(date_str, "%d.%m.%y %H:%M")
        return dt_obj.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except:
        return ""


def _extract_size(text):
    m = re.match(r"(\d+(?:[.,]\d+)?)\s*([A-Za-z]+)", text)
    if not m:
        raise ValueError(f"Invalid size format: {text!r}")
    size_str = m.group(1).replace(",", ".")
    sizeunit = m.group(2)
    size_float = float(size_str)  # convert to float here
    return {"size": size_float, "sizeunit": sizeunit}
