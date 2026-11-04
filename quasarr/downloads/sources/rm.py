# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import string
import threading
import time
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, UnicodeDammit

from quasarr.constants import (
    DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    FLARESOLVERR_REQUEST_TIMEOUT_SECONDS,
    IMDB_REGEX,
    SEARCH_FANOUT_DEADLINE_SECONDS,
    SHARE_HOSTERS_LOWERCASE,
)
from quasarr.downloads.mirror_filters import normalize_mirror_token
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.cloudflare import (
    LazyFlareSolverrSession,
    is_cloudflare_challenge,
)
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import info
from quasarr.providers.utils import is_flaresolverr_available

_URL_REGEX = re.compile(r"https?://\S+")
_RAW_TEXT_TAGS = (
    "script",
    "style",
    "textarea",
    "title",
    "xmp",
    "iframe",
    "noembed",
    "noframes",
    "noscript",
    "plaintext",
)
# matched against lowercased markup
_OPENER_REGEX = re.compile(
    r"<!--|<!\[cdata\[|<(?:" + "|".join(_RAW_TEXT_TAGS) + r")(?=[\s/>])"
)
_OPENER_CLOSERS = {"<!--": "-->", "<![cdata[": "]]>"}
# str.lower() may change the length of non-ASCII text and misplace the matches
_ASCII_LOWERCASE = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


class Source(AbstractDownloadSource):
    initials = "rm"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        slug = _extract_release_slug(url)
        if not slug:
            mark_hostname_issue(Source.initials, "download", "Invalid release URL")
            return {"links": [], "imdb_id": None}

        try:
            soup = _fetch_release_page(
                shared_state,
                slug,
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            raw_links = _extract_download_links(soup)
            links = _extract_download_links(soup, mirrors)
            imdb_id = _extract_imdb_id(soup)

            if raw_links:
                clear_hostname_issue(Source.initials)
            else:
                mark_hostname_issue(
                    Source.initials,
                    "download",
                    "No supported download links found",
                )

            return {"links": links, "imdb_id": imdb_id}
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # a removed release is gone for good, which says nothing about the host
                info(f"Release page for {title or slug} no longer exists")
                return {"links": [], "imdb_id": None}
            info(f"Could not load release data for {title or slug}: {e}")
            mark_hostname_issue(Source.initials, "download", str(e))
            return {"links": [], "imdb_id": None}
        except Exception as e:
            info(f"Could not load release data for {title or slug}: {e}")
            mark_hostname_issue(Source.initials, "download", str(e))
            return {"links": [], "imdb_id": None}

    def get_package_identity(self, url: str) -> str | None:
        return _extract_release_slug(url)


def _get_base_url(shared_state):
    host = shared_state.values["config"]("Hostnames").get(Source.initials)
    if not host:
        return None

    normalized = str(host).strip()
    if "://" in normalized:
        parsed = urlparse(normalized)
        normalized = parsed.netloc or parsed.path

    normalized = normalized.rstrip("/")
    if normalized.startswith("www."):
        normalized = normalized[4:]

    return f"https://{normalized}"


def _build_headers(shared_state):
    return {"User-Agent": shared_state.values["user_agent"]}


# keep-alive across requests; headers go per request so concurrent searches share no mutable state
_SESSION = requests.Session()
_SECURITY_CHECK_LOCK = threading.Lock()
_security_checks_passed = 0


def _get_page(shared_state, path, timeout):
    return BeautifulSoup(_get_markup(shared_state, path, timeout), "html.parser")


def _get_markup(shared_state, path, timeout):
    content = _get_content(shared_state, path, timeout)
    return _escape_unclosed_openers(UnicodeDammit(content, is_html=True).unicode_markup)


def _escape_unclosed_openers(markup):
    """Escape comment and raw-text openers that are not closed before the next one.

    Page texts (the random banner on every page, release descriptions) may carry
    raw markup. A stray opener in one of them would turn the rest of the page
    into plain text and hide every release and link after it.
    """
    lowered = markup.translate(_ASCII_LOWERCASE)
    pieces = []
    position = 0
    while match := _OPENER_REGEX.search(lowered, position):
        opener = match.group(0)
        closer = _OPENER_CLOSERS.get(opener, f"</{opener[1:]}")
        end = lowered.find(closer, match.end())
        next_opener = lowered.find(opener, match.end())
        if end == -1 or -1 < next_opener < end:
            pieces.append(markup[position : match.start()] + "&lt;")
            position = match.start() + 1
        else:
            pieces.append(markup[position : end + len(closer)])
            position = end + len(closer)
    pieces.append(markup[position:])
    return "".join(pieces)


def _get_content(shared_state, path, timeout):
    base_url = _get_base_url(shared_state)
    if not base_url:
        raise ValueError("Missing hostname configuration")

    url = urljoin(f"{base_url}/", path.lstrip("/"))

    # one retry after a second for transient failures (connection, timeout, 5xx)
    for attempt in range(2):
        try:
            response = _SESSION.get(
                url, headers=_build_headers(shared_state), timeout=timeout
            )
            if _is_security_check(response):
                response = _pass_security_check(shared_state, url, timeout, response)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt:
                raise
        else:
            if response.status_code < 500 or attempt:
                response.raise_for_status()
                return response.content
        time.sleep(1)


def _is_security_check(response):
    return response.status_code == 403 or is_cloudflare_challenge(response.text)


def _pass_security_check(shared_state, url, timeout, checked_response):
    """Pass the site's security check once and reuse its cookie for plain requests."""
    if not is_flaresolverr_available(shared_state):
        raise ValueError(
            "The site shows a security check to this server; "
            "configure FlareSolverr to pass it"
        )

    global _security_checks_passed
    seen = _security_checks_passed
    started = time.monotonic()
    # one solve at a time: parallel requests wait here and reuse its cookie
    with _SECURITY_CHECK_LOCK:
        if _security_checks_passed != seen:
            checked_response = _SESSION.get(
                url, headers=_build_headers(shared_state), timeout=timeout
            )
            if not _is_security_check(checked_response):
                return checked_response

        solver = LazyFlareSolverrSession(shared_state)
        try:
            response = solver.get(
                url,
                headers=_build_headers(shared_state),
                timeout=max(timeout, FLARESOLVERR_REQUEST_TIMEOUT_SECONDS),
                # the check was just seen; go straight to FlareSolverr
                request_get=lambda *_args, **_kwargs: checked_response,
            )
        finally:
            solver.close()
        _SESSION.cookies.update(response.cookies)
        _security_checks_passed += 1

    elapsed = time.monotonic() - started
    if elapsed > SEARCH_FANOUT_DEADLINE_SECONDS:
        info(
            f"Passing the security check took {elapsed:.0f}s, longer than "
            "Radarr and Sonarr wait for search results, so this search may come "
            "back without RM. That is expected for the first request after the "
            "check; the following ones reuse it and answer normally."
        )
    return response


def _build_release_page_url(base_url, slug):
    return urljoin(f"{base_url}/", f"release/{slug}")


def _fetch_release_page(shared_state, slug, timeout):
    return _get_page(shared_state, f"release/{slug}", timeout)


def _extract_release_slug(url):
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return None

    path = parsed.path.rstrip("/")
    if "/release/" not in path:
        return None

    return unquote(path.rsplit("/", 1)[-1]) or None


def _extract_download_links(soup, mirrors=None):
    """Read the plain-text link blocks of a release page.

    Every block holds one URL per line. The same upload is often mirrored on
    several domains of one hoster (same path, other TLD), so a file counts once
    per hoster.
    """
    requested = {normalize_mirror_token(mirror) for mirror in (mirrors or []) if mirror}
    requested.discard("")

    links = []
    seen = set()

    for block in soup.select("pre.links"):
        for href in _URL_REGEX.findall(block.get_text("\n")):
            mirror = normalize_mirror_token(href)
            if mirror not in SHARE_HOSTERS_LOWERCASE:
                continue
            if requested and mirror not in requested:
                continue

            identity = (mirror, urlparse(href).path)
            if identity in seen:
                continue
            seen.add(identity)
            links.append([href, mirror])

    return links


def _extract_imdb_id(soup):
    for anchor in soup.find_all("a", href=IMDB_REGEX):
        match = IMDB_REGEX.search(anchor["href"])
        if match:
            return match.group(1)

    return None
