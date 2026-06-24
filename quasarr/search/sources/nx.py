# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import time

import requests

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
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
    normalize_magazine_title,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "nx"
    language = "de"
    requires_account = True
    supports_imdb = True
    supports_phrase = True
    supported_categories = [
        SEARCH_CAT_BOOKS,
        SEARCH_CAT_MOVIES,
        SEARCH_CAT_SHOWS,
        SEARCH_CAT_MUSIC,
    ]
    requires_login = True

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []
        nx = shared_state.values["config"]("Hostnames").get(self.initials)
        password = nx

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            stype = "ebook"
        elif base_search_category == SEARCH_CAT_MOVIES:
            stype = "movie"
        elif base_search_category == SEARCH_CAT_SHOWS:
            stype = "episode"
        elif base_search_category == SEARCH_CAT_MUSIC:
            stype = "audio"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        url = f"https://{nx}/api/frontend/releases/category/{stype}/tag/all/1/51?sort=date"
        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        try:
            r = requests.get(url, headers, timeout=FEED_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            feed = r.json()
        except Exception as e:
            warn(f"Error loading feed: {e}")
            mark_hostname_issue(
                self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
            )
            return releases

        items = feed["result"]["list"]
        for item in items:
            try:
                title = item["name"]

                if title:
                    try:
                        if base_search_category == SEARCH_CAT_BOOKS:
                            # magazarr can only detect specific date formats / issue numbering for magazines
                            title = normalize_magazine_title(title)

                        source = f"https://{nx}/release/{item['slug']}"
                        imdb_id = item.get("_media", {}).get("imdbid", None)
                        mb = convert_to_mb(item)

                        link = generate_download_link(
                            shared_state,
                            title,
                            source,
                            mb,
                            password,
                            imdb_id,
                            self.initials,
                        )
                    except:
                        continue

                    try:
                        size = mb * 1024 * 1024
                    except:
                        continue

                    try:
                        published = item["publishat"]
                    except:
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
                warn(f"Error parsing feed: {e}")
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
        """
        Search using internal API.
        Deduplicates results by fulltitle - each unique release appears only once.
        """
        releases = []
        nx = shared_state.values["config"]("Hostnames").get(self.initials)
        password = nx

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            valid_type = "ebook"
        elif base_search_category == SEARCH_CAT_MOVIES:
            valid_type = "movie"
        elif base_search_category == SEARCH_CAT_SHOWS:
            valid_type = "episode"
        elif base_search_category == SEARCH_CAT_MUSIC:
            valid_type = "audio"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

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

        url = f"https://{nx}/api/frontend/search/{search_string}"
        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        try:
            r = requests.get(url, headers, timeout=SEARCH_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            feed = r.json()
        except Exception as e:
            warn(f"Error loading search: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            return releases

        items = feed["result"]["releases"]
        for item in items:
            try:
                if item["type"] == valid_type:
                    title = item["name"]
                    if title:
                        if not is_valid_release(
                            title, search_category, search_string, season, episode
                        ):
                            continue

                        if base_search_category == SEARCH_CAT_BOOKS:
                            # magazarr can only detect specific date formats / issue numbering for magazines
                            title = normalize_magazine_title(title)

                        try:
                            source = f"https://{nx}/release/{item['slug']}"
                            release_imdb_id = item.get("_media", {}).get("imdbid", None)
                            if (
                                imdb_id
                                and release_imdb_id
                                and release_imdb_id != imdb_id
                            ):
                                trace(
                                    f"Skipping result '{title}' due to IMDb ID mismatch."
                                )
                                continue

                            if release_imdb_id is None:
                                release_imdb_id = imdb_id

                            mb = convert_to_mb(item)

                            link = generate_download_link(
                                shared_state,
                                title,
                                source,
                                mb,
                                password,
                                release_imdb_id,
                                self.initials,
                            )
                        except:
                            continue

                        try:
                            size = mb * 1024 * 1024
                        except:
                            continue

                        try:
                            published = item["publishat"]
                        except:
                            published = ""

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
                warn(f"Error parsing search: {e}")
                mark_hostname_issue(
                    self.initials,
                    "search",
                    str(e) if "e" in dir() else "Error occurred",
                )

        elapsed_time = time.time() - start_time
        debug(f"Time taken: {elapsed_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases
