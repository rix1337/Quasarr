# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.cloudflare import LazyFlareSolverrSession
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info, warn
from quasarr.providers.utils import detect_crypter_type


class Source(AbstractDownloadSource):
    initials = "ff"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        cf_session = LazyFlareSolverrSession(shared_state)
        try:
            return self._get_download_links(
                shared_state, url, mirrors, title, password, cf_session
            )
        finally:
            cf_session.close()

    def _get_download_links(
        self, shared_state, url, mirrors, title, password, cf_session
    ):
        host = shared_state.values["config"]("Hostnames").get(Source.initials)
        user_agent = shared_state.values["user_agent"]

        if url.startswith(f"https://{host}/external"):
            resolved_url = _resolve_ff_redirect(url, user_agent, host, cf_session)
            if not resolved_url:
                return {"links": [], "imdb_id": None}
            return {
                "links": [[resolved_url, _mirror_from_url(resolved_url)]],
                "imdb_id": None,
            }

        if not url.startswith(f"https://{host}/"):
            return {"links": [], "imdb_id": None}

        try:
            headers = {"User-Agent": user_agent}
            r = cf_session.get(
                url,
                headers,
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                request_get=requests.get,
            )
            r.raise_for_status()
            page = r.text
            soup = BeautifulSoup(page, "html.parser")

            imdb_id = None
            imdb_link = soup.find("a", href=re.compile(r"imdb\.com/title/tt\d+"))
            if imdb_link:
                match = re.search(r"tt\d+", imdb_link["href"])
                if match:
                    imdb_id = match.group()

            token_match = re.search(r"initMovie\('([^']+)'", page)
            if not token_match:
                return {"links": [], "imdb_id": imdb_id}

            r = cf_session.get(
                f"https://{host}/api/v1/{token_match.group(1)}?filter=",
                headers,
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                request_get=requests.get,
            )
            r.raise_for_status()
            content = BeautifulSoup(r.json().get("html", ""), "html.parser")

            requested_title = title or _title_from_url(url)
            for entry in content.select("div.entry"):
                release_title = _entry_title(entry)
                if not release_title or not _same_title(release_title, requested_title):
                    continue

                release_url, mirror_name = _select_release_link(
                    f"https://{host}", entry, mirrors
                )
                if not release_url:
                    return {"links": [], "imdb_id": imdb_id}

                resolved_url = _resolve_ff_redirect(
                    release_url, user_agent, host, cf_session
                )
                if not resolved_url:
                    return {"links": [], "imdb_id": imdb_id}

                info(f'Release "{release_title}" found at: {url}')
                return {"links": [[resolved_url, mirror_name]], "imdb_id": imdb_id}
        except Exception as e:
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )

        return {"links": [], "imdb_id": None}


def _entry_title(entry):
    title = entry.select_one("span.morespec")
    return title.get_text(strip=True) if title else ""


def _title_from_url(url):
    return unquote(url.rstrip("/").split("/")[-1])


def _same_title(left, right):
    return str(left or "").strip().lower() == str(right or "").strip().lower()


def _select_release_link(base_url, entry, mirrors):
    links = []
    for anchor in entry.select("a.dlb.row[href]"):
        mirror = anchor.select_one("div.col span")
        mirror_name = mirror.get_text(strip=True).lower() if mirror else ""
        links.append((urljoin(base_url, anchor["href"]), mirror_name or "direct"))

    if not links:
        return None, None

    if mirrors:
        for wanted in mirrors:
            wanted = wanted.lower()
            for release_url, mirror_name in links:
                if wanted in mirror_name:
                    return release_url, mirror_name
        info(f"Could not find any of mirrors '{mirrors}'")
        return None, None

    return links[0]


# Shopping/affiliate hosts that filmfans' hostile ad redirects to instead of the
# real file hoster (Quasarr#419: the /external redirect yields an aliexpress landing
# page, which then reaches the mirror whitelist / JDownloader as the "download").
# Kept narrow so a genuine hoster or crypter redirect is never dropped; matched on a
# domain-label boundary so it cannot false-positive on a hoster that merely contains
# the text.
_AD_REDIRECT_HOST_MARKERS = ("aliexpress.", "temu.", "banggood.")

# Re-resolutions when the /external redirect is hijacked to an ad host. The ad is
# intermittent, so a couple of fresh attempts usually reach the real hoster; a
# deterministic hijack simply fails cleanly instead of yielding the ad link.
_FF_RESOLVE_ATTEMPTS = 3


def _is_ad_redirect_host(url):
    """True when ``url`` points at a known ad/affiliate host, not a file hoster."""
    host = (urlparse(url).netloc or "").lower()
    if not host:
        return False
    return any(marker in host + "." for marker in _AD_REDIRECT_HOST_MARKERS)


def _resolve_ff_redirect(url, user_agent, host, cf_session):
    for attempt in range(1, _FF_RESOLVE_ATTEMPTS + 1):
        outcome, resolved = _resolve_ff_redirect_once(url, user_agent, host, cf_session)
        if outcome == "ok":
            return resolved
        if outcome != "hijacked":
            return None
        warn(
            "FF link resolved to a hostile-ad domain instead of a file hoster; "
            f"re-resolving ({attempt}/{_FF_RESOLVE_ATTEMPTS}): <d>{url}</d>"
        )
    warn(f"FF link kept resolving to a hostile-ad domain; giving up: <d>{url}</d>")
    return None


def _resolve_ff_redirect_once(url, user_agent, host, cf_session):
    """Follow the /external redirect chain once.

    Returns ``(outcome, resolved_url)``:
      * ``("ok", url)``        a crypter or real hoster link to hand on
      * ``("hijacked", None)`` a hostile ad steered us to an affiliate host (retryable)
      * ``("fail", None)``     404 / error / IP-ban / loop (not retryable)
    """
    current_url = url
    visited = set()
    session = requests.Session()
    source_netloc = urlparse(f"https://{host}").netloc

    for _hop in range(8):
        if current_url in visited:
            debug(f"FF redirect loop detected for {current_url}")
            return "fail", None
        visited.add(current_url)

        if detect_crypter_type(current_url) is not None:
            return "ok", current_url

        try:
            r = cf_session.get(
                current_url,
                {"User-Agent": user_agent},
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                request_get=lambda request_url, headers, timeout: session.get(
                    request_url,
                    allow_redirects=False,
                    timeout=timeout,
                    headers=headers,
                ),
            )
        except Exception as e:
            warn(f"Error fetching redirected URL for {url}: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )
            return "fail", None

        location = (r.headers.get("Location") or "").strip()
        if location:
            next_url = urljoin(current_url, location)
            debug(f"Redirected from <d>{current_url}</d> to <d>{next_url}</d>")
            if "/404.html" in next_url:
                warn(f"Link redirected to 404 page: <d>{next_url}</d>")
                return "fail", None
            if _is_ad_redirect_host(next_url):
                debug(f"FF redirect steered to ad host: <d>{next_url}</d>")
                return "hijacked", None
            if detect_crypter_type(next_url) is not None:
                return "ok", next_url
            if urlparse(next_url).netloc != source_netloc:
                return "ok", next_url
            current_url = next_url
            continue

        final_url = (r.url or current_url).strip()
        if "/404.html" in final_url:
            warn(f"Link redirected to 404 page: <d>{final_url}</d>")
            return "fail", None
        if r.status_code >= 400:
            warn(
                f"Error fetching redirected URL for {url}: HTTP {r.status_code} at {final_url}"
            )
            mark_hostname_issue(
                Source.initials,
                "download",
                f"HTTP {r.status_code} while resolving redirect",
            )
            return "fail", None
        if _is_ad_redirect_host(final_url):
            debug(f"FF link landed on ad host: <d>{final_url}</d>")
            return "hijacked", None
        if detect_crypter_type(final_url) is not None:
            return "ok", final_url
        if urlparse(final_url).netloc != source_netloc:
            return "ok", final_url
        warn(
            f"Blocked attempt to resolve {url}. Your IP may be banned. Try again later."
        )
        return "fail", None

    debug(f"FF redirect hop limit exceeded for {url}")
    return "fail", None


def _mirror_from_url(url):
    host = urlparse(url).netloc.lower()
    if not host:
        return "direct"
    labels = host.split(".")
    return labels[-2] if len(labels) >= 2 else labels[0]
