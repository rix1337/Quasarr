# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info

hostname = "he"


def get_he_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    HE source handler - fetches plain download links from HE pages.
    """

    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    session = requests.Session()

    try:
        r = session.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        info(f"{hostname}: could not fetch release for {title}: {e}")
        mark_hostname_issue(
            hostname, "download", str(e) if "e" in dir() else "Download error"
        )
        return {"links": [], "imdb_id": None}

    imdb_id = None
    try:
        imdb_link = soup.find(
            "a", href=re.compile(r"imdb\.com/title/tt\d+", re.IGNORECASE)
        )
        if imdb_link:
            href = imdb_link["href"].strip()
            m = re.search(r"(tt\d{4,7})", href)
            if m:
                imdb_id = m.group(1)
            else:
                debug(f"{hostname}: imdb_id not found for title {title} in link href.")
        else:
            debug(f"{hostname}: imdb_id link href not found for title {title}.")
    except Exception:
        debug(f"{hostname}: failed to extract imdb_id for title {title}.")

    anchors = []
    for retries in range(10):
        form = soup.find("form", id=re.compile(r"content-protector-access-form"))
        if not form:
            return {"links": [], "imdb_id": None}

        action = form.get("action") or url
        action_url = urljoin(r.url, action)

        payload = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            value = inp.get("value", "")
            payload[name] = value

        append_patt = re.compile(
            r"append\(\s*[\'\"](?P<key>[^\'\"]+)[\'\"]\s*,\s*[\'\"](?P<val>[^\'\"]+)[\'\"]\s*\)",
            re.IGNORECASE,
        )

        for script in soup.find_all("script"):
            txt = script.string if script.string is not None else script.get_text()
            if not txt:
                continue
            for m in append_patt.finditer(txt):
                payload[m.group("key")] = m.group("val")

        post_headers = headers.copy()
        post_headers.update({"Referer": r.url})
        try:
            r = session.post(action_url, data=payload, headers=post_headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            info(f"{hostname}: could not submit protector form for {title}: {e}")
            mark_hostname_issue(
                hostname, "download", str(e) if "e" in dir() else "Download error"
            )
            break

        unlocked = soup.select(".content-protector-access-form")
        if unlocked:
            for u in unlocked:
                anchors.extend(u.find_all("a", href=True))

        if anchors:
            break

    links = []
    for a in anchors:
        try:
            href = a["href"].strip()

            netloc = urlparse(href).netloc
            hoster = netloc.split(":")[0].lower()
            parts = hoster.split(".")
            if len(parts) >= 2:
                hoster = parts[-2]

            links.append([href, hoster])
        except Exception:
            debug(f"{hostname}: could not resolve download link hoster for {title}")
            continue

    if not links:
        info(f"No external download links found on {hostname} page for {title}")
        return {"links": [], "imdb_id": None}

    return {
        "links": links,
        "imdb_id": imdb_id,
    }
