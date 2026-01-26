# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timezone

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info
from quasarr.providers.sessions.dd import (
    create_and_persist_session,
    retrieve_and_validate_session,
)

hostname = "dd"
supported_mirrors = ["ironfiles", "rapidgator", "filefactory"]


def convert_to_rss_date(unix_timestamp):
    parsed_date = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    rss_date = parsed_date.strftime("%a, %d %b %Y %H:%M:%S %z")

    return rss_date


def extract_size(size_in_bytes):
    return {"size": size_in_bytes, "sizeunit": "B"}


def dd_feed(*args, **kwargs):
    return dd_search(*args, **kwargs)


def dd_search(
    shared_state,
    start_time,
    request_from,
    search_string="",
    mirror=None,
    season=None,
    episode=None,
):
    releases = []
    dd = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = dd

    if not "arr" in request_from.lower():
        debug(
            f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!'
        )
        return releases

    try:
        dd_session = retrieve_and_validate_session(shared_state)
    except Exception as e:
        mark_hostname_issue(hostname, "search", str(e))
        return releases

    if not dd_session:
        info(f"Could not retrieve valid session for {dd}")
        return releases

    if mirror and mirror not in supported_mirrors:
        debug(
            f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
            " Skipping search!"
        )
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        search_string = get_localized_title(shared_state, imdb_id, "en")
        if not search_string:
            info(f"Could not extract title from IMDb-ID {imdb_id}")
            return releases
        search_string = html.unescape(search_string)

    if not search_string:
        search_type = "feed"
        timeout = 30
    else:
        search_type = "search"
        timeout = 10

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
                        f"Release {release.get('release')} marked as fake. Invalidating {hostname.upper()} session..."
                    )
                    create_and_persist_session(shared_state)
                    return []
                else:
                    title = release.get("release")

                    if not shared_state.is_valid_release(
                        title, request_from, search_string, season, episode
                    ):
                        continue

                    imdb_id = release.get("imdbid", None)

                    source = f"https://{dd}/"
                    size_item = extract_size(release.get("size"))
                    mb = shared_state.convert_to_mb(size_item) * 1024 * 1024
                    published = convert_to_rss_date(release.get("when"))
                    payload = urlsafe_b64encode(
                        f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}|{hostname}".encode(
                            "utf-8"
                        )
                    ).decode("utf-8")
                    link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                    releases.append(
                        {
                            "details": {
                                "title": title,
                                "hostname": hostname.lower(),
                                "imdb_id": imdb_id,
                                "link": link,
                                "mirror": mirror,
                                "size": mb,
                                "date": published,
                                "source": source,
                            },
                            "type": "protected",
                        }
                    )
            except Exception as e:
                info(f"Error parsing {hostname.upper()} feed: {e}")
                mark_hostname_issue(
                    hostname, "search", str(e) if "e" in dir() else "Error occurred"
                )
                continue

    except Exception as e:
        info(f"Error loading {hostname.upper()} {search_type}: {e}")
        mark_hostname_issue(
            hostname, search_type, str(e) if "e" in dir() else "Error occurred"
        )

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases
