# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    IMDB_REGEX,
    SHARE_HOSTERS_LOWERCASE,
)
from quasarr.downloads.mirror_filters import normalize_mirror_token
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import info

_URL_REGEX = re.compile(r"https?://\S+")


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
            links = _extract_download_links(soup, mirrors)
            imdb_id = _extract_imdb_id(soup)

            if links:
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


def _get_page(shared_state, path, timeout):
    base_url = _get_base_url(shared_state)
    if not base_url:
        raise ValueError("Missing hostname configuration")

    response = requests.get(
        urljoin(f"{base_url}/", path.lstrip("/")),
        headers=_build_headers(shared_state),
        timeout=timeout,
    )
    response.raise_for_status()
    return BeautifulSoup(response.content, "html.parser")


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
