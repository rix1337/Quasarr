# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.sessions.dd import (
    create_and_persist_session,
    retrieve_and_validate_session,
)

hostname = "dd"


def get_dd_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    Returns plain download links from DD API.
    """

    dd = shared_state.values["config"]("Hostnames").get("dd")

    dd_session = retrieve_and_validate_session(shared_state)
    if not dd_session:
        info(f"Could not retrieve valid session for {dd}")
        mark_hostname_issue(hostname, "download", "Session error")
        return {"links": []}

    links = []

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
            api_url = f"https://{dd}/index/search/keyword/{title}/qualities/{','.join(qualities)}/from/{page}/search"

            r = dd_session.get(api_url, headers=headers, timeout=10)
            r.raise_for_status()
            releases_on_page = r.json()
            if releases_on_page:
                release_list.extend(releases_on_page)

        for release in release_list:
            try:
                if release.get("fake"):
                    debug(
                        f"Release {release.get('release')} marked as fake. Invalidating DD session..."
                    )
                    create_and_persist_session(shared_state)
                    return {"links": []}
                elif release.get("release") == title:
                    filtered_links = []
                    for link in release["links"]:
                        if mirror and mirror not in link["hostname"]:
                            debug(
                                f'Skipping link from "{link["hostname"]}" (not the desired mirror "{mirror}")!'
                            )
                            continue

                        if any(
                            existing_link["hostname"] == link["hostname"]
                            and existing_link["url"].endswith(".mkv")
                            and link["url"].endswith(".mkv")
                            for existing_link in filtered_links
                        ):
                            debug(
                                f"Skipping duplicate `.mkv` link from {link['hostname']}"
                            )
                            continue
                        filtered_links.append(link)

                    # Build [[url, mirror], ...] format
                    links = [[link["url"], link["hostname"]] for link in filtered_links]
                    break
            except Exception as e:
                info(f"Error parsing DD download: {e}")
                mark_hostname_issue(
                    hostname, "download", str(e) if "e" in dir() else "Download error"
                )
                continue

    except Exception as e:
        info(f"Error loading DD download: {e}")
        mark_hostname_issue(
            hostname, "download", str(e) if "e" in dir() else "Download error"
        )

    return {"links": links}
