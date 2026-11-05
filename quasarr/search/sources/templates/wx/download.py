# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import requests

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import check_links_online_status

# WX publishes filecrypt and hide.cx as mirror crypters of the same container
# id. Uploads from these WX user ids are always also published on hide.cx, so
# their filecrypt.cc containers can be rewritten to the hide.cx twin and resolved
# automatically via hide.py without a CAPTCHA. This mirrors the WX frontend
# exactly: app.js gates the identical `filecrypt.cc -> hide.cx/fc` rewrite on
# `[4].includes(mirror.user)`, where `mirror.user` is the release `user_id`.
HIDE_CX_MIRROR_USER_IDS = {4}


def _collect_online_direct_links(release, mirrors, shared_state):
    """
    Build ready-to-use direct download links for a single mirror from the WX
    'links' field (plain hoster URLs, no crypter/CAPTCHA needed).

    Uses the same filecrypt status badges (options.check) that WX itself uses
    to display green/red status on their site, identical to the crypted-links
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

        # All parts for the same hoster share one badge, so probe once and apply to all.
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

    def get_package_identity(self, url):
        """Identify a selected release without including mutable URL details."""
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        if any(
            len(query.get(key, [])) != 1 for key in ("release", "season", "episode")
        ):
            return None
        release_uid = query["release"][0]
        try:
            season = int(query["season"][0])
            episode = int(query["episode"][0])
        except (TypeError, ValueError):
            return None
        if not release_uid or season < 0 or episode <= 0:
            return None
        return f"{release_uid}:S{season:02d}E{episode:02d}"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        WX source handler. Picks the mirror/link set with the best
        source-provided online signal and hands it to JDownloader; it never
        probes a direct hoster link itself (liveness is JDownloader's job).

        Priority (rationale: .trail/learnings/21-mirror-selection-ownership.md):
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

            # Quasarr owns the episode parameters; the upstream page receives
            # only its existing release selector.
            page_parts = urlsplit(url)
            page_query = parse_qs(page_parts.query, keep_blank_values=True)
            page_url = url
            if "season" in page_query or "episode" in page_query:
                page_query.pop("season", None)
                page_query.pop("episode", None)
                page_url = urlunsplit(
                    page_parts._replace(query=urlencode(page_query, doseq=True))
                )
            # First, load the page to establish session cookies
            r = session.get(
                page_url,
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
            query = parse_qs(urlsplit(url).query, keep_blank_values=True)
            episode_selection = None
            if "season" in query or "episode" in query:
                try:
                    if any(
                        len(query.get(key, [])) != 1
                        for key in ("release", "season", "episode")
                    ):
                        raise ValueError("Ambiguous episode selection")
                    selected_season = int(query["season"][0])
                    selected_episode = int(query["episode"][0])
                    selected_uid = query["release"][0]
                    if selected_season < 0 or selected_episode <= 0:
                        raise ValueError("Invalid episode selection")
                except (KeyError, IndexError, ValueError):
                    return {
                        "links": [],
                        "error": "Episode not present in link container",
                        "terminal": True,
                    }
                episode_selection = (selected_season, selected_episode)
                matching_releases = []
                for release in releases:
                    original_title = html.unescape(
                        release.get("fulltitle") or ""
                    ).replace(" ", ".")
                    pack_token = rf"(?i)(?<![a-z0-9])S0*{selected_season}(?![a-z0-9])"
                    candidate = re.sub(
                        pack_token,
                        f"S{selected_season:02d}E{selected_episode:02d}",
                        original_title,
                        count=1,
                    )
                    if str(release.get("uid")) == selected_uid and candidate == title:
                        matching_releases.append(release)
            else:
                matching_releases = [r for r in releases if r.get("fulltitle") == title]

            if not matching_releases:
                info(f"No release found matching title: {title}")
                if episode_selection:
                    return {
                        "links": [],
                        "error": "Episode not present in link container",
                        "terminal": True,
                    }
                return {"links": []}

            debug(f"Found {len(matching_releases)} mirror(s) for: {title}")

            # Rationale: .trail/learnings/21-mirror-selection-ownership.md.
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
                # See HIDE_CX_MIRROR_USER_IDS: for these uploaders a filecrypt.cc
                # container is also published on hide.cx under the same id, so we
                # use the hide twin (auto-resolved, no CAPTCHA) - exactly what the
                # WX frontend does for `mirror.user`.
                user_id = release.get("user_id")
                mirror_to_hide = user_id in HIDE_CX_MIRROR_USER_IDS

                hide_candidates = []  # [container_url, hoster, status_url]
                fc_candidates = []
                for hoster, container_url in crypted_links.items():
                    if mirrors and not any(
                        m.lower() in hoster.lower() for m in mirrors
                    ):
                        continue
                    state_url = check_urls.get(hoster)
                    if mirror_to_hide and "filecrypt.cc" in container_url.lower():
                        container_url = re.sub(
                            r"filecrypt\.cc",
                            "hide.cx/fc",
                            container_url,
                            flags=re.IGNORECASE,
                        )
                    if episode_selection:
                        if urlsplit(container_url).hostname != "hide.cx":
                            continue
                        parts = urlsplit(container_url)
                        container_query = parse_qs(parts.query)
                        container_query.update(
                            season=[str(episode_selection[0])],
                            episode=[str(episode_selection[1])],
                        )
                        container_url = urlunsplit(
                            parts._replace(query=urlencode(container_query, doseq=True))
                        )
                    if re.search(r"hide\.", container_url, re.IGNORECASE):
                        hide_candidates.append([container_url, hoster, state_url])
                    elif re.search(r"filecrypt\.", container_url, re.IGNORECASE):
                        fc_candidates.append([container_url, hoster, state_url])
                    # Other crypters are unsupported and ignored.

                # Only containers that actually carry a status badge are
                # eligible for the certified-online tiers. A container without a
                # badge is not certified online (check_links_online_status would
                # treat a missing status URL as online), so it must not outrank a
                # badge-green direct link or another mirror; it stays a no-signal
                # last resort (tier 4) instead.
                hide_badged = [c for c in hide_candidates if c[2] is not None]
                fc_badged = [c for c in fc_candidates if c[2] is not None]

                # Tier 1 candidate: this mirror's online hide.cx containers.
                online_hide = (
                    check_links_online_status(hide_badged, shared_state)
                    if hide_badged
                    else []
                )
                if online_hide and (
                    best_hide is None or len(online_hide) > best_hide[0]
                ):
                    best_hide = (len(online_hide), online_hide)

                if episode_selection:
                    if red_hide is None and hide_candidates:
                        red_hide = [hide_candidates[0][0], hide_candidates[0][1]]
                    continue

                # Tier 2 candidate: this mirror's online filecrypt containers.
                online_fc = (
                    check_links_online_status(fc_badged, shared_state)
                    if fc_badged
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
                        # Keep ALL parts of this hoster: a WX direct hoster can
                        # be a multipart archive, so a single URL is an
                        # incomplete mirror that JDownloader cannot finish.
                        parts = [
                            [u.strip(), hoster]
                            for u in urls
                            if isinstance(u, str) and u.strip()
                        ]
                        if parts:
                            red_direct = parts
                            break

            # Tier 1: green hide.cx containers from the best single mirror.
            if best_hide:
                debug(
                    f"Tier 1: {best_hide[0]} online hide.cx container(s) "
                    f"- handing to JDownloader"
                )
                return {"links": best_hide[1]}

            if episode_selection:
                if red_hide:
                    return {"links": [red_hide]}
                return {
                    "links": [],
                    "error": "Episode not present in link container",
                    "terminal": True,
                }

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
            # Containers are complete on their own (one URL); a direct mirror
            # keeps all its parts.
            if red_hide:
                red_links = [red_hide]
            elif red_fc:
                red_links = [red_fc]
            else:
                red_links = red_direct
            if red_links:
                debug(
                    "Tier 4: no online signal; handing first offline-flagged "
                    "mirror to JDownloader as last resort"
                )
                return {"links": red_links}

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
