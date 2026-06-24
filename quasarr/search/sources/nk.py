# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, info, trace
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    is_imdb_id,
    is_valid_release,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "nk"
    language = "de"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]

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

        source_search = ""
        if search_string != "":
            imdb_id = is_imdb_id(search_string)
            if imdb_id:
                local_title = get_localized_title(shared_state, imdb_id, "de")
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

        url = f"https://{host}/search"
        headers = {"User-Agent": shared_state.values["user_agent"]}
        data = {"search": source_search}

        try:
            r = requests.post(url, headers=headers, data=data, timeout=timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            results = soup.find_all("div", class_="article-right")
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
                a = result.find("a", class_="release-details", href=True)
                if not a:
                    continue

                sub_title = result.find("span", class_="subtitle")
                if sub_title:
                    title = sub_title.get_text(strip=True)
                else:
                    continue

                release_imdb_id = None
                imdb_a = result.select_one("a.imdb")
                if imdb_a and imdb_a.get("href"):
                    try:
                        release_imdb_id = re.search(r"tt\d+", imdb_a["href"]).group()
                        if imdb_id and release_imdb_id and release_imdb_id != imdb_id:
                            trace(
                                f"IMDb ID mismatch: expected {imdb_id}, found {release_imdb_id}"
                            )
                            continue
                    except Exception:
                        debug(f"failed to determine imdb_id for {title}")
                else:
                    trace(f"imdb link not found for {title}")

                if release_imdb_id is None:
                    release_imdb_id = imdb_id

                if not is_valid_release(
                    title, search_category, search_string, season, episode
                ):
                    continue

                source = urljoin(f"https://{host}", a["href"])

                mb = 0
                size_text = _get_release_field(result, "Größe")
                if size_text:
                    size_item = _extract_size(size_text)
                    mb = convert_to_mb(size_item)

                if season != "" and episode == "":
                    mb = 0  # Size unknown for season packs

                size = mb * 1024 * 1024

                password = ""
                mirrors_p = result.find("p", class_="mirrors")
                if mirrors_p:
                    strong = mirrors_p.find("strong")
                    if strong and strong.get_text(strip=True).lower().startswith(
                        "passwort"
                    ):
                        nxt = strong.next_sibling
                        if nxt:
                            val = str(nxt).strip()
                            if val:
                                password = val.split()[0]

                date_text = ""
                p_meta = result.find("p", class_="meta")
                if p_meta:
                    spans = p_meta.find_all("span")
                    if len(spans) >= 2:
                        date_part = spans[0].get_text(strip=True)
                        time_part = (
                            spans[1].get_text(strip=True).replace("Uhr", "").strip()
                        )
                        date_text = f"{date_part} / {time_part}"

                published = _convert_to_rss_date(date_text) if date_text else ""

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
                info(e)
                debug(f"error parsing search result: {e}")
                continue

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")
        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _convert_to_rss_date(date_str: str) -> str:
    date_str = date_str.strip()
    for fmt in (
        "%d. %B %Y / %H:%M",
        "%d.%m.%Y / %H:%M",
        "%d.%m.%Y - %H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            continue
    return ""


def _extract_size(text: str) -> dict:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*([A-Za-z]+)", text)
    if match:
        size = match.group(1).replace(",", ".")
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}
    return {"size": "0", "sizeunit": "MB"}


def _get_release_field(res, label):
    for li in res.select("ul.release-infos li"):
        sp = li.find("span")
        if not sp:
            return ""
        if sp.get_text(strip=True).lower() == label.lower():
            txt = li.get_text(" ", strip=True)
            return txt[len(sp.get_text(strip=True)) :].strip()
    return ""
