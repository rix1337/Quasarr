# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from base64 import urlsafe_b64encode
from datetime import datetime, timezone

from quasarr.downloads.sources.dd import create_and_persist_session, retrieve_and_validate_session


def convert_to_rss_date(unix_timestamp):
    parsed_date = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    rss_date = parsed_date.strftime('%a, %d %b %Y %H:%M:%S %z')

    return rss_date


def extract_size(size_in_bytes):
    return {"size": size_in_bytes, "sizeunit": "B"}


def dd_search(shared_state, search_string=""):
    dd = shared_state.values["config"]("Hostnames").get("dd")

    dd_session = retrieve_and_validate_session(shared_state)
    if not dd_session:
        print(f"Could not retrieve valid session for {dd}")
        return []

    releases = []
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

            releases_on_page = dd_session.get(url, headers=headers).json()
            if releases_on_page:
                release_list.extend(releases_on_page)

        for release in release_list:
            try:
                if release.get("fake"):
                    if shared_state.debug():
                        print(f"Release {release.get('release')} marked as fake. Invalidating DD session...")
                        create_and_persist_session(shared_state)
                        return []
                else:
                    title = release.get("release")

                    if not shared_state.search_string_in_sanitized_title(search_string, title):
                        continue

                    source = f"https://{dd}/"
                    size_item = extract_size(release.get("size"))
                    mb = shared_state.convert_to_mb(size_item) * 1024 * 1024
                    published = convert_to_rss_date(release.get("when"))
                    payload = urlsafe_b64encode(f"{title}|{source}|{mb}|{password}".encode("utf-8")).decode(
                        "utf-8")
                    link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                    releases.append({
                        "details": {
                            "title": f"[DD] {title}",
                            "link": link,
                            "size": mb,
                            "date": published,
                            "source": source
                        },
                        "type": "protected"
                    })
            except Exception as e:
                print(f"Error parsing DD feed: {e}")
                continue

    except Exception as e:
        print(f"Error loading DD feed: {e}")

    return releases
