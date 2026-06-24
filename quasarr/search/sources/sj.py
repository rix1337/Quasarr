# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_ANIME,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info, trace
from quasarr.providers.utils import (
    generate_download_link,
    is_imdb_id,
    is_valid_release,
    sanitize_string,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "sj"
    language = "de"
    requires_account = True
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_SHOWS, SEARCH_CAT_SHOWS_ANIME]
    requires_login = True

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []

        sj_host = shared_state.values["config"]("Hostnames").get(self.initials)
        password = sj_host

        headers = {"User-Agent": shared_state.values["user_agent"]}

        for days in range(4):
            url = f"https://{sj_host}/api/releases/latest/{days}"

            try:
                r = requests.get(
                    url, headers=headers, timeout=FEED_REQUEST_TIMEOUT_SECONDS
                )
                r.raise_for_status()
                data = json.loads(r.content)
            except Exception as e:
                info(f"feed load error: {e}")
                mark_hostname_issue(
                    self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
                )
                return releases

            for release in data:
                try:
                    title = release.get("name").rstrip(".")
                    if not title:
                        continue

                    published = _convert_to_rss_date(release.get("createdAt"))
                    if not published:
                        continue

                    media = release.get("_media", {})
                    slug = media.get("slug")
                    if not slug:
                        continue

                    series_url = f"https://{sj_host}/serie/{slug}"

                    mb = 0
                    size = 0
                    imdb_id = None

                    link = generate_download_link(
                        shared_state,
                        title,
                        series_url,
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
                                "source": series_url,
                            },
                            "type": "protected",
                        }
                    )

                except Exception as e:
                    debug(f"feed parse error: {e}")
                    continue

            if releases:
                break

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
        releases = []

        sj_host = shared_state.values["config"]("Hostnames").get(self.initials)
        password = sj_host

        imdb_id = is_imdb_id(search_string)
        if not imdb_id:
            return releases

        localized_title = get_localized_title(shared_state, imdb_id, "de")
        if not localized_title:
            info(f"no localized title for IMDb {imdb_id}")
            return releases

        headers = {"User-Agent": shared_state.values["user_agent"]}
        search_url = f"https://{sj_host}/serie/search"
        params = {"q": localized_title}

        try:
            r = requests.get(
                search_url,
                headers=headers,
                params=params,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            results = soup.find_all("a", href=re.compile(r"^/serie/"))
        except Exception as e:
            info(f"search load error: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            return releases

        one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        sanitized_search_string = sanitize_string(localized_title)

        for result in results:
            try:
                result_title = result.get_text(strip=True)

                sanitized_title = sanitize_string(result_title)

                if not re.search(
                    rf"\b{re.escape(sanitized_search_string)}\b", sanitized_title
                ):
                    trace(
                        f"Search string '{localized_title}' doesn't match '{result_title}'"
                    )
                    continue

                trace(
                    f"Matched search string '{localized_title}' with result '{result_title}'"
                )

                series_url = f"https://{sj_host}{result['href']}"

                r = requests.get(
                    series_url,
                    headers=headers,
                    timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                )
                r.raise_for_status()
                media_id_match = re.search(r'data-mediaid="([^"]+)"', r.text)
                if not media_id_match:
                    debug(f"no media id for {result_title}")
                    continue

                media_id = media_id_match.group(1)
                api_url = f"https://{sj_host}/api/media/{media_id}/releases"

                r = requests.get(
                    api_url,
                    headers=headers,
                    timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                )
                r.raise_for_status()
                data = json.loads(r.content)

                for season_block in data.values():
                    for item in season_block.get("items", []):
                        title = item.get("name").rstrip(".")
                        if not title:
                            continue

                        if not is_valid_release(
                            title, search_category, search_string, season, episode
                        ):
                            continue

                        published = _convert_to_rss_date(item.get("createdAt"))
                        if not published:
                            debug(f"no published date for {title}")
                            published = one_hour_ago

                        mb = 0
                        size = 0

                        link = generate_download_link(
                            shared_state,
                            title,
                            series_url,
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
                                    "source": series_url,
                                },
                                "type": "protected",
                            }
                        )

            except Exception as e:
                debug(f"search parse error: {e}")
                continue

        debug(f"Time taken: {time.time() - start_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _convert_to_rss_date(date_str):
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )
    except Exception:
        return ""
