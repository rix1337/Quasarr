# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import time
from datetime import datetime, timezone

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
from quasarr.providers.log import debug, error, info, warn
from quasarr.providers.sessions.dd import (
    create_and_persist_session,
    retrieve_and_validate_session,
)
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    is_imdb_id,
    is_valid_release,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "dd"
    language = "en"
    requires_account = True
    invite_only = True
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS, SEARCH_CAT_SHOWS_ANIME]
    requires_login = True

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        return self.search(shared_state, start_time, search_category, "")

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
        dd = shared_state.values["config"]("Hostnames").get(self.initials)
        password = dd

        try:
            dd_session = retrieve_and_validate_session(shared_state)
        except Exception as e:
            mark_hostname_issue(self.initials, "search", str(e))
            return releases

        if not dd_session:
            info(f"Could not retrieve valid session for {dd}")
            return releases

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            search_string = get_localized_title(shared_state, imdb_id, "en")
            if not search_string:
                info(f"Could not extract title from IMDb-ID {imdb_id}")
                return releases
            search_string = html.unescape(search_string)
            if season:
                search_string += f" S{int(season):02d}"
                if episode:
                    search_string += f"E{int(episode):02d}"
            else:
                if year := get_year(imdb_id):
                    search_string += f" {year}"

        if not search_string:
            search_type = "feed"
            timeout = FEED_REQUEST_TIMEOUT_SECONDS
        else:
            search_type = "search"
            timeout = SEARCH_REQUEST_TIMEOUT_SECONDS

        qualities = [
            "disk-480p",
            "web-480p",
            "movie-480p-x265",
            "disk-1080p-x265",
            "web-1080p",
            "web-1080p-x265",
            "web-2160p-x265-hdr",
            "movie-1080p-x265",
            "movie-2160p-webdl-x265-hdr",
        ]

        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        try:
            release_list = []
            for page in range(0, 100, 20):
                url = f"https://{dd}/index/search/keyword/{search_string}/qualities/{','.join(qualities)}/from/{page}/search"

                r = dd_session.get(url, headers=headers, timeout=timeout)
                r.raise_for_status()
                releases_on_page = r.json()
                if releases_on_page:
                    release_list.extend(releases_on_page)

            for release in release_list:
                try:
                    if release.get("fake"):
                        debug(
                            f"Release {release.get('release')} marked as fake. Invalidating session..."
                        )
                        create_and_persist_session(shared_state)
                        return []
                    else:
                        title = release.get("release")

                        if not is_valid_release(
                            title, search_category, search_string, season, episode
                        ):
                            continue

                        release_imdb = release.get("imdbid", None)
                        if release_imdb and imdb_id and imdb_id != release_imdb:
                            debug(
                                f"Release {title} IMDb-ID mismatch ({imdb_id} != {release.get('imdbid', None)})"
                            )
                            continue

                        source = f"https://{dd}/"
                        size_item = _extract_size(release.get("size"))
                        mb = convert_to_mb(size_item) * 1024 * 1024
                        published = _convert_to_rss_date(release.get("when"))

                        link = generate_download_link(
                            shared_state,
                            title,
                            source,
                            mb,
                            password,
                            release_imdb,
                            self.initials,
                        )

                        releases.append(
                            {
                                "details": {
                                    "title": title,
                                    "hostname": self.initials,
                                    "imdb_id": imdb_id,
                                    "link": link,
                                    "size": mb,
                                    "date": published,
                                    "source": source,
                                },
                                "type": "protected",
                            }
                        )
                except Exception as e:
                    warn(f"Error parsing feed: {e}")
                    mark_hostname_issue(
                        self.initials,
                        "search",
                        str(e) if "e" in dir() else "Error occurred",
                    )
                    continue

        except Exception as e:
            error(f"Error loading feed: {e}")
            mark_hostname_issue(
                self.initials, search_type, str(e) if "e" in dir() else "Error occurred"
            )

        elapsed_time = time.time() - start_time
        debug(f"Time taken: {elapsed_time:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _convert_to_rss_date(unix_timestamp):
    parsed_date = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    rss_date = parsed_date.strftime("%a, %d %b %Y %H:%M:%S %z")

    return rss_date


def _extract_size(size_in_bytes):
    return {"size": size_in_bytes, "sizeunit": "B"}
