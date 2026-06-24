# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import time
import traceback
import warnings
from datetime import datetime

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

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
from quasarr.providers.log import debug, error, trace, warn
from quasarr.providers.utils import (
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    is_valid_release,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource

warnings.filterwarnings(
    "ignore", category=XMLParsedAsHTMLWarning
)  # we dont want to use lxml


class Source(AbstractSearchSource):
    initials = "wx"
    language = "de"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS, SEARCH_CAT_SHOWS_ANIME]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        """
        Fetch latest releases from RSS feed.
        """
        releases = []
        host = shared_state.values["config"]("Hostnames").get(self.initials)

        rss_url = f"https://{host}/rss"
        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        try:
            r = requests.get(
                rss_url,
                headers=headers,
                timeout=FEED_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()

            soup = BeautifulSoup(r.content, "html.parser")
            items = soup.find_all("entry")

            if not items:
                items = soup.find_all("item")

            if not items:
                warn("No entries found in RSS feed")
                return releases

            trace(f"Found {len(items)} entries in RSS feed")

            for item in items:
                try:
                    title_tag = item.find("title")
                    if not title_tag:
                        continue

                    title = title_tag.get_text(strip=True)
                    if not title:
                        continue

                    title = html.unescape(title)
                    title = title.replace("]]>", "").replace("<![CDATA[", "")
                    title = title.replace(" ", ".")

                    link_tag = item.find("link", rel="alternate")
                    if link_tag and link_tag.has_attr("href"):
                        source = link_tag["href"]
                    else:
                        link_tag = item.find("link")
                        if not link_tag:
                            continue
                        source = link_tag.get_text(strip=True)

                    if not source:
                        continue

                    pub_date = item.find("updated") or item.find("pubDate")
                    if pub_date:
                        published = pub_date.get_text(strip=True)
                    else:
                        # Fallback: use current time if no pubDate found
                        published = datetime.now().strftime(
                            "%a, %d %b %Y %H:%M:%S +0000"
                        )

                    mb = 0
                    size = 0
                    imdb_id = None
                    password = host.upper()

                    link = generate_download_link(
                        shared_state,
                        title,
                        source,
                        mb,
                        password,
                        imdb_id or "",
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
                    debug(f"Error parsing RSS entry: {e}")
                    continue

        except Exception as e:
            error(f"Error loading feed: {e}")
            mark_hostname_issue(
                self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
            )
            return releases

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
        host = shared_state.values["config"]("Hostnames").get(self.initials)

        base_search_category = get_base_search_category_id(search_category)

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            debug(f"Received IMDb ID: <y>{imdb_id}</y>")
            title = get_localized_title(shared_state, imdb_id, "de")
            if not title:
                error(f"No title found for IMDb '{imdb_id}'")
                return releases
            trace(f"Resolved IMDb '{imdb_id}' to: '{title}'")
            search_string = html.unescape(title)
        else:
            debug(f"Using search string directly: '{search_string}'")

        api_url = f"https://api.{host}/start/search"

        headers = {
            "User-Agent": shared_state.values["user_agent"],
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://{host}/search",
        }

        params = {
            "__LOAD_P": "",
            "per_page": 50,
            "q": search_string,
            "selectedTypes": "",
            "selectedGenres": "",
            "types": "movie,series,anime",
            "genres": "",
            "years": year if (year := get_year(imdb_id)) else "",
            "ratings": "",
            "page": 1,
            "sortBy": "latest",
            "sortOrder": "desc",
        }

        if base_search_category == SEARCH_CAT_SHOWS:
            params["types"] = "series,anime"
            if search_category == SEARCH_CAT_SHOWS_ANIME:
                params["types"] = "anime"
        elif base_search_category == SEARCH_CAT_MOVIES:
            params["types"] = "movie"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        trace(f"Searching: '{search_string}'")

        try:
            r = requests.get(
                api_url,
                headers=headers,
                params=params,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()

            data = r.json()

            if "items" in data and "data" in data["items"]:
                items = data["items"]["data"]
            elif "data" in data:
                items = data["data"]
            elif "results" in data:
                items = data["results"]
            else:
                items = data if isinstance(data, list) else []

            trace(f"Found {len(items)} items in search results")

            # Track seen titles to deduplicate (mirrors have same fulltitle)
            seen_titles = set()

            for item in items:
                try:
                    uid = item.get("uid")
                    if not uid:
                        debug("Item has no UID, skipping")
                        continue

                    trace(f"Fetching details for UID: {uid}")

                    detail_url = f"https://api.{host}/start/d/{uid}"
                    detail_r = requests.get(
                        detail_url,
                        headers=headers,
                        timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                    )
                    detail_r.raise_for_status()

                    detail_data = detail_r.json()

                    if "item" in detail_data:
                        detail_item = detail_data["item"]
                    else:
                        detail_item = detail_data

                    item_imdb_id = detail_item.get("imdb_id") or detail_item.get(
                        "imdbid"
                    )
                    if not item_imdb_id and "options" in detail_item:
                        item_imdb_id = detail_item["options"].get("imdb_id")

                    if item_imdb_id and imdb_id and item_imdb_id != imdb_id:
                        debug(
                            f"IMDb-ID mismatch ({imdb_id} != {item_imdb_id}), skipping item"
                        )
                        continue

                    if item_imdb_id is None:
                        item_imdb_id = imdb_id

                    source = f"https://{host}/detail/{uid}"

                    main_title = (
                        detail_item.get("fulltitle")
                        or detail_item.get("title")
                        or detail_item.get("name")
                    )
                    if main_title:
                        title = html.unescape(main_title)
                        title = title.replace(" ", ".")

                        if is_valid_release(
                            title, search_category, search_string, season, episode
                        ):
                            # Skip if we've already seen this exact title
                            if title in seen_titles:
                                debug(f"Skipping duplicate main title: {title}")
                            else:
                                seen_titles.add(title)
                                published = detail_item.get(
                                    "updated_at"
                                ) or detail_item.get("created_at")
                                if not published:
                                    published = datetime.now().strftime(
                                        "%a, %d %b %Y %H:%M:%S +0000"
                                    )
                                password = f"www.{host}"

                                link = generate_download_link(
                                    shared_state,
                                    title,
                                    source,
                                    0,
                                    password,
                                    item_imdb_id,
                                    self.initials,
                                )

                                releases.append(
                                    {
                                        "details": {
                                            "title": title,
                                            "hostname": self.initials,
                                            "imdb_id": item_imdb_id,
                                            "link": link,
                                            "size": 0,
                                            "date": published,
                                            "source": source,
                                        },
                                        "type": "protected",
                                    }
                                )

                    if "releases" in detail_item and isinstance(
                        detail_item["releases"], list
                    ):
                        trace(
                            f"Found {len(detail_item['releases'])} releases for {uid}"
                        )

                        for release in detail_item["releases"]:
                            try:
                                release_title = release.get("fulltitle")
                                if not release_title:
                                    continue

                                release_title = html.unescape(release_title)
                                release_title = release_title.replace(" ", ".")

                                if not is_valid_release(
                                    release_title,
                                    search_category,
                                    search_string,
                                    season,
                                    episode,
                                ):
                                    continue

                                # Skip if we've already seen this exact title (deduplication)
                                if release_title in seen_titles:
                                    trace(
                                        f"Skipping duplicate release: {release_title}"
                                    )
                                    continue

                                seen_titles.add(release_title)

                                release_uid = release.get("uid")
                                if release_uid:
                                    release_source = f"https://{host}/detail/{uid}?release={release_uid}"
                                else:
                                    release_source = source

                                release_published = (
                                    release.get("updated_at")
                                    or release.get("created_at")
                                    or detail_item.get("updated_at")
                                )
                                if not release_published:
                                    release_published = datetime.now().strftime(
                                        "%a, %d %b %Y %H:%M:%S +0000"
                                    )
                                release_size = release.get("size", 0)
                                password = f"www.{host}"

                                link = generate_download_link(
                                    shared_state,
                                    release_title,
                                    release_source,
                                    release_size,
                                    password,
                                    item_imdb_id,
                                    self.initials,
                                )

                                releases.append(
                                    {
                                        "details": {
                                            "title": release_title,
                                            "hostname": self.initials,
                                            "imdb_id": item_imdb_id,
                                            "link": link,
                                            "size": release_size,
                                            "date": release_published,
                                            "source": release_source,
                                        },
                                        "type": "protected",
                                    }
                                )

                            except Exception as e:
                                debug(f"Error parsing release: {e}")
                                continue
                    else:
                        debug(f"No releases array found for {uid}")

                except Exception as e:
                    debug(f"Error processing item: {e}")
                    debug(f"{traceback.format_exc()}")
                    continue

            trace(f"Returning {len(releases)} total releases (deduplicated)")

        except Exception as e:
            error(f"Error in search: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )

            debug(f"{traceback.format_exc()}")
            return releases

        elapsed_time = time.time() - start_time
        debug(f"Time taken: {elapsed_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases
