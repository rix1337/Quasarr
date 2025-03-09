# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timezone

from quasarr.downloads.sources.dd import create_and_persist_session, retrieve_and_validate_session
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "dd"
supported_mirrors = ["ironfiles", "rapidgator", "filefactory"]


def convert_to_rss_date(unix_timestamp):
    parsed_date = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    rss_date = parsed_date.strftime('%a, %d %b %Y %H:%M:%S %z')

    return rss_date


def extract_size(size_in_bytes):
    return {"size": size_in_bytes, "sizeunit": "B"}


def dd_search(shared_state, start_time, search_string="", mirror=None):
    releases = []
    dd = shared_state.values["config"]("Hostnames").get(hostname.lower())

    dd_session = retrieve_and_validate_session(shared_state)
    if not dd_session:
        info(f"Could not retrieve valid session for {dd}")
        return releases

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
              ' Skipping search!')
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        search_string = get_localized_title(shared_state, imdb_id, 'en')
        if not search_string:
            info(f"Could not extract title from IMDb-ID {imdb_id}")
            return releases
        search_string = html.unescape(search_string)

    password = dd

    qualities = [
        "disk-480p",
        "web-480p",
        "movie-480p-x265",
        "disk-1080p-x265",
        "web-1080p",
        "web-1080p-x265",
        "web-2160p-x265-hdr",
        "movie-1080p-x265",
        "movie-2160p-webdl-x265-hdr"
    ]

    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        release_list = []
        for page in range(0, 100, 20):
            url = f'https://{dd}/index/search/keyword/{search_string}/qualities/{','.join(qualities)}/from/{page}/search'

            releases_on_page = dd_session.get(url, headers=headers, timeout=10).json()
            if releases_on_page:
                release_list.extend(releases_on_page)

        for release in release_list:
            try:
                if release.get("fake"):
                    debug(
                        f"Release {release.get('release')} marked as fake. Invalidating {hostname.upper()} session...")
                    create_and_persist_session(shared_state)
                    return []
                else:
                    title = release.get("release")

                    if search_string and not shared_state.search_string_in_sanitized_title(search_string, title):
                        continue

                    imdb_id = release.get("imdbid", None)

                    source = f"https://{dd}/"
                    size_item = extract_size(release.get("size"))
                    mb = shared_state.convert_to_mb(size_item) * 1024 * 1024
                    published = convert_to_rss_date(release.get("when"))
                    payload = urlsafe_b64encode(
                        f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode("utf-8")
                    link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                    releases.append({
                        "details": {
                            "title": title,
                            "hostname": hostname.lower(),
                            "imdb_id": imdb_id,
                            "link": link,
                            "mirror": mirror,
                            "size": mb,
                            "date": published,
                            "source": source
                        },
                        "type": "protected"
                    })
            except Exception as e:
                info(f"Error parsing {hostname.upper()} feed: {e}")
                continue

    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds ({hostname.lower()})")

    return releases
