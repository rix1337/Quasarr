# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info

hostname = "sl"
supported_mirrors = ["nitroflare", "ddownload"]


def derive_mirror_from_host(host):
    """Get mirror name from hostname."""
    for m in supported_mirrors:
        if host.startswith(m + "."):
            return m
    return host.split(".")[0] if host else "unknown"


def get_sl_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    SL source handler - returns plain download links.
    """
    headers = {"User-Agent": shared_state.values["user_agent"]}
    session = requests.Session()

    try:
        r = session.get(url, headers=headers, timeout=10)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        entry = soup.find("div", class_="entry")
        if not entry:
            info(f"Could not find main content section for {title}")
            mark_hostname_issue(
                hostname, "download", "Could not find main content section"
            )
            return {"links": [], "imdb_id": None}

        imdb_id = None
        a_imdb = soup.find("a", href=re.compile(r"imdb\.com/title/tt\d+"))
        if a_imdb:
            m = re.search(r"(tt\d+)", a_imdb["href"])
            if m:
                imdb_id = m.group(1)
                debug(f"Found IMDb id: {imdb_id}")

        download_h2 = entry.find(
            lambda t: t.name == "h2" and "download" in t.get_text(strip=True).lower()
        )
        if download_h2:
            anchors = []
            for sib in download_h2.next_siblings:
                if getattr(sib, "name", None) == "h2":
                    break
                if hasattr(sib, "find_all"):
                    anchors += sib.find_all("a", href=True)
        else:
            anchors = entry.find_all("a", href=True)

    except Exception as e:
        info(
            f"SL site has been updated. Grabbing download links for {title} not possible! ({e})"
        )
        mark_hostname_issue(hostname, "download", str(e))
        return {"links": [], "imdb_id": None}

    filtered = []
    for a in anchors:
        href = a["href"].strip()
        if not href.lower().startswith(("http://", "https://")):
            continue

        host = (urlparse(href).hostname or "").lower()
        if not any(host.startswith(m + ".") for m in supported_mirrors):
            continue

        if not mirror or mirror in href:
            mirror_name = derive_mirror_from_host(host)
            filtered.append([href, mirror_name])

    # regex fallback if still empty
    if not filtered:
        text = "".join(str(x) for x in anchors)
        urls = re.findall(r"https?://[^\s<>'\"]+", text)
        seen = set()
        for u in urls:
            u = u.strip()
            if u in seen:
                continue
            seen.add(u)

            host = (urlparse(u).hostname or "").lower()
            if not any(host.startswith(m + ".") for m in supported_mirrors):
                continue

            if not mirror or mirror in u:
                mirror_name = derive_mirror_from_host(host)
                filtered.append([u, mirror_name])

    if filtered:
        clear_hostname_issue(hostname)
    return {
        "links": filtered,
        "imdb_id": imdb_id,
    }
