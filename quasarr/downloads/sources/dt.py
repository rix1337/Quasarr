# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import info


class Source(AbstractDownloadSource):
    initials = "dt"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        DT source handler - returns plain download links.
        """
        headers = {"User-Agent": shared_state.values["user_agent"]}
        session = requests.Session()

        try:
            r = session.get(
                url,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            body = soup.find("div", class_="full-story-body")
            if not body:
                info(f"Could not find download section for {title}")
                mark_hostname_issue(
                    Source.initials, "download", "Could not find download section"
                )
                return None

            anchors = body.find_all("a", href=True)

        except Exception as e:
            info(
                f"Site has been updated. Grabbing download links for {title} not possible! ({e})"
            )
            mark_hostname_issue(Source.initials, "download", str(e))
            return None

        filtered = []
        for a in anchors:
            href = a["href"].strip()

            if not href.lower().startswith(("http://", "https://")):
                continue
            lower = href.lower()
            if "imdb.com" in lower or "?ref=" in lower:
                continue
            if mirrors and not any(m in href for m in mirrors):
                continue

            mirror_name = _derive_mirror_from_url(href)
            filtered.append([href, mirror_name])

        # regex fallback if still empty
        if not filtered:
            text = body.get_text(separator="\n")
            urls = re.findall(r'https?://[^\s<>"\']+', text)
            seen = set()
            for u in urls:
                u = u.strip()
                if u not in seen:
                    seen.add(u)
                    low = u.lower()
                    if (
                        low.startswith(("http://", "https://"))
                        and "imdb.com" not in low
                        and "?ref=" not in low
                    ):
                        if not mirrors or any(m in u for m in mirrors):
                            mirror_name = _derive_mirror_from_url(u)
                            filtered.append([u, mirror_name])

        if filtered:
            clear_hostname_issue(Source.initials)
        return {"links": filtered} if filtered else None


def _derive_mirror_from_url(url):
    """Extract hoster name from URL hostname."""
    try:
        mirror_hostname = urlparse(url).netloc.lower()
        if mirror_hostname.startswith("www."):
            mirror_hostname = mirror_hostname[4:]
        parts = mirror_hostname.split(".")
        if len(parts) >= 2:
            return parts[-2]
        return mirror_hostname
    except:
        return "unknown"
