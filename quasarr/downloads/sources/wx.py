# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests

from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import check_links_online_status

hostname = "wx"


def get_wx_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    WX source handler - Grabs download links from API based on title.
    Finds the best mirror (M1, M2, M3...) by checking online status.
    Returns all online links from the first complete mirror, or the best partial mirror.
    Prefers hide.cx links over other crypters (filecrypt, etc.) when online counts are equal.
    """
    host = shared_state.values["config"]("Hostnames").get(hostname)

    headers = {
        "User-Agent": shared_state.values["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        session = requests.Session()

        # First, load the page to establish session cookies
        r = session.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        # Extract slug from URL
        slug_match = re.search(r"/detail/([^/?]+)", url)
        if not slug_match:
            info(f"{hostname.upper()}: Could not extract slug from URL: {url}")
            return {"links": []}

        api_url = f"https://api.{host}/start/d/{slug_match.group(1)}"

        # Update headers for API request
        api_headers = {
            "User-Agent": shared_state.values["user_agent"],
            "Accept": "application/json",
        }

        debug(f"{hostname.upper()}: Fetching API data from: {api_url}")
        api_r = session.get(api_url, headers=api_headers, timeout=30)
        api_r.raise_for_status()

        data = api_r.json()

        # Navigate to releases in the API response
        if "item" not in data or "releases" not in data["item"]:
            info(f"{hostname.upper()}: No releases found in API response")
            return {"links": []}

        releases = data["item"]["releases"]

        # Find ALL releases matching the title (these are different mirrors: M1, M2, M3...)
        matching_releases = [r for r in releases if r.get("fulltitle") == title]

        if not matching_releases:
            info(f"{hostname.upper()}: No release found matching title: {title}")
            return {"links": []}

        debug(
            f"{hostname.upper()}: Found {len(matching_releases)} mirror(s) for: {title}"
        )

        # Evaluate each mirror and find the best one
        # Track: (online_count, is_hide, online_links)
        best_mirror = None  # (online_count, is_hide, online_links)

        for idx, release in enumerate(matching_releases):
            crypted_links = release.get("crypted_links", {})
            check_urls = release.get("options", {}).get("check", {})

            if not crypted_links:
                continue

            # Separate hide.cx links from other crypters
            hide_links = []
            other_links = []

            for hoster, container_url in crypted_links.items():
                state_url = check_urls.get(hoster)
                if re.search(r"hide\.", container_url, re.IGNORECASE):
                    hide_links.append([container_url, hoster, state_url])
                elif re.search(r"filecrypt\.", container_url, re.IGNORECASE):
                    other_links.append([container_url, hoster, state_url])
                # Skip other crypters we don't support

            # Check hide.cx links first (preferred)
            hide_online = 0
            online_hide = []
            if hide_links:
                online_hide = check_links_online_status(hide_links, shared_state)
                hide_total = len(hide_links)
                hide_online = len(online_hide)

                debug(
                    f"{hostname.upper()}: M{idx + 1} hide.cx: {hide_online}/{hide_total} online"
                )

                # If all hide.cx links are online, use this mirror immediately
                if hide_online == hide_total and hide_online > 0:
                    debug(
                        f"{hostname.upper()}: M{idx + 1} is complete (all {hide_online} hide.cx links online), using this mirror"
                    )
                    return {"links": online_hide}

            # Check other crypters (filecrypt, etc.) - no early return, always check all mirrors for hide.cx first
            other_online = 0
            online_other = []
            if other_links:
                online_other = check_links_online_status(other_links, shared_state)
                other_total = len(other_links)
                other_online = len(online_other)

                debug(
                    f"{hostname.upper()}: M{idx + 1} other crypters: {other_online}/{other_total} online"
                )

            # Determine best option for this mirror (prefer hide.cx on ties)
            mirror_links = None
            mirror_count = 0
            mirror_is_hide = False

            if hide_online > 0 and hide_online >= other_online:
                # hide.cx wins (more links or tie)
                mirror_links = online_hide
                mirror_count = hide_online
                mirror_is_hide = True
            elif other_online > hide_online:
                # other crypter has more online links
                mirror_links = online_other
                mirror_count = other_online
                mirror_is_hide = False

            # Update best_mirror if this mirror is better
            # Priority: 1) more online links, 2) hide.cx preference on ties
            if mirror_links:
                if best_mirror is None:
                    best_mirror = (mirror_count, mirror_is_hide, mirror_links)
                elif mirror_count > best_mirror[0]:
                    best_mirror = (mirror_count, mirror_is_hide, mirror_links)
                elif (
                    mirror_count == best_mirror[0]
                    and mirror_is_hide
                    and not best_mirror[1]
                ):
                    # Same count but this is hide.cx and current best is not
                    best_mirror = (mirror_count, mirror_is_hide, mirror_links)

        # No complete mirror found, return best partial mirror
        if best_mirror and best_mirror[2]:
            crypter_type = "hide.cx" if best_mirror[1] else "other crypter"
            debug(
                f"{hostname.upper()}: No complete mirror, using best partial with {best_mirror[0]} online {crypter_type} link(s)"
            )
            return {"links": best_mirror[2]}

        info(f"{hostname.upper()}: No online links found for: {title}")
        return {"links": []}

    except Exception as e:
        info(f"{hostname.upper()}: Error extracting download links from {url}: {e}")
        mark_hostname_issue(
            hostname, "download", str(e) if "e" in dir() else "Download error"
        )
        return {"links": []}
