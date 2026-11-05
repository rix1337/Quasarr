# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.downloads.sources.helpers.junkies import _release_matches_requested_mirrors
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import info


class Source(AbstractDownloadSource):
    initials = "sj"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        SJ source handler - the site itself acts as a protected crypter.
        Returns the URL for CAPTCHA solving via userscript.
        """
        try:
            if not _release_matches_requested_mirrors(
                url, mirrors, shared_state.values["user_agent"], title
            ):
                info(f"No requested mirrors are available for {title}")
                return {"links": []}
        except Exception as e:
            info(f"Error checking mirrors for {title}: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )
            return {"links": []}

        return {"links": [[url, "junkies"]]}
