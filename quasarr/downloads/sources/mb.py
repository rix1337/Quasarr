# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info

hostname = "mb"


def get_mb_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    MB source handler - fetches protected download links from MB pages.
    """

    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as e:
        info(f"Failed to fetch page for {title or url}: {e}")
        mark_hostname_issue(hostname, "download", str(e))
        return {"links": []}

    soup = BeautifulSoup(r.text, "html.parser")

    download_links = []

    pattern = re.compile(
        r"https?://(?:www\.)?filecrypt\.[^/]+/Container/", re.IGNORECASE
    )
    for a in soup.find_all("a", href=pattern):
        try:
            link = a["href"]
            hoster = a.get_text(strip=True).lower()

            if mirror and mirror.lower() not in hoster.lower():
                debug(
                    f'Skipping link from "{hoster}" (not the desired mirror "{mirror}")!'
                )
                continue

            download_links.append([link, hoster])
        except Exception as e:
            debug(f"Error parsing MB download links: {e}")

    if not download_links:
        info(
            f"No download links found for {title}. Site structure may have changed. - {url}"
        )
        mark_hostname_issue(
            hostname,
            "download",
            "No download links found - site structure may have changed",
        )
        return {"links": []}

    clear_hostname_issue(hostname)
    return {"links": download_links}
