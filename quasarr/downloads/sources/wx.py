# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import check_links_online_status


def _collect_online_direct_links(release, mirrors, shared_state):
    """
    Build ready-to-use direct download links for a single mirror from the WX
    'links' field (plain hoster URLs, no crypter/CAPTCHA needed).

    Uses the same filecrypt status badges (options.check) that WX itself uses
    to display green/red status on their site — identical to the crypted-links
    path. HEAD-probing the hoster URLs directly is unreliable: premium hosters
    return HTTP 200 (or redirect to a login page that also resolves 200) for
    deleted files, making every mirror look online regardless of actual state.

    Returns (online_hoster_count, links) where links is a flat
    [[url, hoster], ...] list covering every hoster whose badge is green.
    """
    links_field = release.get("links", {}) or {}
    check_urls = release.get("options", {}).get("check", {}) or {}

    links_with_status = []

    for hoster, urls in links_field.items():
        # Honor the requested mirror whitelist (hoster names).
        if mirrors and not any(m.lower() in hoster.lower() for m in mirrors):
            continue

        if not isinstance(urls, list):
            urls = [urls]
        clean = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
        if not clean:
            continue

        # All parts for the same hoster share one badge — probe once, apply to all.
        status_url = check_urls.get(hoster)
        for u in clean:
            links_with_status.append([u, hoster, status_url])

    if not links_with_status:
        return 0, []

    online_links = check_links_online_status(links_with_status, shared_state)
    online_hosters = len(set(link[1] for link in online_links))

    return online_hosters, online_links


class Source(AbstractDownloadSource):
    initials = "wx"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        WX source handler. Picks the mirror/link set with the best
        source-provided online signal and hands it to JDownloader; it never
        probes a direct hoster link itself (liveness is JDownloader's job).

        Priority (see docs/Mirror-Selection.md):
          1. green hide.cx container   (resolved downstream by hide.py, no CAPTCHA)
          2. green filecrypt container (handed to JDownloader, may need CAPTCHA)
          3. green direct links        (no badge of their own; best effort)
          4. first offline-flagged mirror as a last resort
        """
        host = shared_state.values["config"]("Hostnames").get(Source.initials)

        headers = {
            "User-Agent": shared_state.values["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            session = requests.Session()

            # First, load the page to establish session cookies
            r = session.get(
                url,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()

            # Extract slug from URL
            slug_match = re.search(r"/detail/([^/?]+)", url)
            if not slug_match:
                info(f"Could not extract slug from URL: {url}")
                return {"links": []}

            api_url = f"https://api.{host}/start/d/{slug_match.group(1)}"

            # Update headers for API request
            api_headers = {
                "User-Agent": shared_state.values["user_agent"],
                "Accept": "application/json",
            }

            debug(f"Fetching API data from: {api_url}")
            api_r = session.get(
                api_url,
                headers=api_headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            api_r.raise_for_status()

            data = api_r.json()

            # Navigate to releases in the API response
            if "item" not in data or "releases" not in data["item"]:
                info("No releases found in API response")
                return {"links": []}

            releases = data["item"]["releases"]

            # Find ALL releases matching the title (these are different mirrors: M1, M2, M3...)
            matching_releases = [r for r in releases if r.get("fulltitle") == title]

            if not matching_releases:
                info(f"No release found matching title: {title}")
                return {"links": []}

            debug(f"Found {len(matching_releases)} mirror(s) for: {title}")

            # SELECTION POLICY (see docs/Mirror-Selection.md):
            # Quasarr picks the link set with the best *source-provided* online
            # signal and hands it to JDownloader. It never probes a direct
            # hoster link itself - liveness is JDownloader's job. WX's status
            # badge (options.check) certifies the crypted *container*, not the
            # separate direct 'links' upload, so containers rank above direct
            # links. A dead pick is expected to fail in JDownloader, which
            # Quasarr reports so Radarr/Sonarr can blacklist and try the next
            # release.
            #
            # Each mirror (M1, M2, ...) is a distinct upload of the release, so
            # link sets are NEVER merged across mirrors - that would enqueue
            # duplicate copies of the same release in JDownloader. We evaluate
            # mirror by mirror and return a single mirror's set. Within that one
            # mirror, every online hoster is kept on purpose (redundant hoster
            # choices for the same files; the automation submits them and the
            # manual flow lets the user pick one).

            # Best single mirror per tier: (online_count, links).
            best_hide = None
            best_fc = None
            best_direct = None
            # Last-resort offline pick, hide > filecrypt > direct preference.
            red_hide = red_fc = red_direct = None

            for release in matching_releases:
                crypted_links = release.get("crypted_links", {}) or {}
                check_urls = release.get("options", {}).get("check", {}) or {}

                hide_candidates = []  # [container_url, hoster, status_url]
                fc_candidates = []
                for hoster, container_url in crypted_links.items():
                    if mirrors and not any(
                        m.lower() in hoster.lower() for m in mirrors
                    ):
                        continue
                    state_url = check_urls.get(hoster)
                    if re.search(r"hide\.", container_url, re.IGNORECASE):
                        hide_candidates.append([container_url, hoster, state_url])
                    elif re.search(r"filecrypt\.", container_url, re.IGNORECASE):
                        fc_candidates.append([container_url, hoster, state_url])
                    # Other crypters are unsupported and ignored.

                # Tier 1 candidate: this mirror's online hide.cx containers.
                online_hide = (
                    check_links_online_status(hide_candidates, shared_state)
                    if hide_candidates
                    else []
                )
                if online_hide and (
                    best_hide is None or len(online_hide) > best_hide[0]
                ):
                    best_hide = (len(online_hide), online_hide)

                # Tier 2 candidate: this mirror's online filecrypt containers.
                online_fc = (
                    check_links_online_status(fc_candidates, shared_state)
                    if fc_candidates
                    else []
                )
                if online_fc and (best_fc is None or len(online_fc) > best_fc[0]):
                    best_fc = (len(online_fc), online_fc)

                # Tier 3 candidate: this mirror's online direct links.
                count, direct_links = _collect_online_direct_links(
                    release, mirrors, shared_state
                )
                if direct_links and (best_direct is None or count > best_direct[0]):
                    best_direct = (count, direct_links)

                # Tier 4 fallbacks: first offline-flagged option of each kind.
                if red_hide is None and hide_candidates:
                    red_hide = [hide_candidates[0][0], hide_candidates[0][1]]
                if red_fc is None and fc_candidates:
                    red_fc = [fc_candidates[0][0], fc_candidates[0][1]]
                if red_direct is None:
                    links_field = release.get("links", {}) or {}
                    for hoster, urls in links_field.items():
                        if mirrors and not any(
                            m.lower() in hoster.lower() for m in mirrors
                        ):
                            continue
                        if not isinstance(urls, list):
                            urls = [urls]
                        for u in urls:
                            if isinstance(u, str) and u.strip():
                                red_direct = [u.strip(), hoster]
                                break
                        if red_direct:
                            break

            # Tier 1: green hide.cx containers from the best single mirror.
            if best_hide:
                debug(
                    f"Tier 1: {best_hide[0]} online hide.cx container(s) "
                    f"- handing to JDownloader"
                )
                return {"links": best_hide[1]}

            # Tier 2: green filecrypt containers from the best single mirror.
            if best_fc:
                debug(
                    f"Tier 2: {best_fc[0]} online filecrypt container(s) "
                    f"- handing to JDownloader"
                )
                return {"links": best_fc[1]}

            # Tier 3: green direct links from the best single mirror.
            if best_direct and best_direct[1]:
                debug(
                    f"Tier 3: {len(best_direct[1])} direct link(s) from best "
                    f"mirror ({best_direct[0]} online hoster(s)) - handing to JDownloader"
                )
                return {"links": best_direct[1]}

            # Tier 4: no online signal anywhere. Hand the first offline-flagged
            # mirror to JDownloader as a last resort (hide > filecrypt > direct)
            # so the release is still attempted and, if dead, fails cleanly into
            # the Radarr/Sonarr blacklist-and-retry path.
            red_first = red_hide or red_fc or red_direct
            if red_first:
                debug(
                    "Tier 4: no online signal; handing first offline-flagged "
                    "mirror to JDownloader as last resort"
                )
                return {"links": [[red_first[0], red_first[1]]]}

            info(f"No links found for: {title}")
            return {"links": []}

        except Exception as e:
            info(f"Error extracting download links from {url}: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )
            return {"links": []}
