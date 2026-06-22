# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337
#
# MX — download twin.
# Original contribution by Riourik (https://github.com/riourik), PR #360.

from urllib.parse import urlparse

from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import clear_hostname_issue
from quasarr.providers.log import debug


class Source(AbstractDownloadSource):
    initials = "mx"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        # The search side already decoded the final hoster URL (1Fichier, Send,
        # ...) into the payload, so there is nothing to fetch here.
        if not url:
            return {"links": []}

        mirror = _derive_mirror_from_url(url)
        if mirrors and not any(m in url for m in mirrors):
            debug(f"[mx] {mirror} not in requested mirrors for {title}")
            return {"links": []}

        debug(f"[mx] download link: {url}")
        clear_hostname_issue(self.initials)
        return {"links": [[url, mirror]]}


def _derive_mirror_from_url(url):
    """Extract the hoster name from a URL hostname."""
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        parts = host.split(".")
        return parts[-2] if len(parts) >= 2 else host
    except Exception:
        return "unknown"
