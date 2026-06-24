# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import detect_crypter_type


class Source(AbstractDownloadSource):
    initials = "ff"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        host = shared_state.values["config"]("Hostnames").get(Source.initials)
        user_agent = shared_state.values["user_agent"]

        if url.startswith(f"https://{host}/external"):
            resolved_url = _resolve_ff_redirect(url, user_agent, host)
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
            r = requests.get(
                url, headers=headers, timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS
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

            r = requests.get(
                f"https://{host}/api/v1/{token_match.group(1)}?filter=",
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
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

                resolved_url = _resolve_ff_redirect(release_url, user_agent, host)
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


def _resolve_ff_redirect(url, user_agent, host):
    current_url = url
    visited = set()
    session = requests.Session()
    source_netloc = urlparse(f"https://{host}").netloc

    for _hop in range(8):
        if current_url in visited:
            debug(f"FF redirect loop detected for {current_url}")
            return None
        visited.add(current_url)

        if detect_crypter_type(current_url) is not None:
            return current_url

        try:
            r = session.get(
                current_url,
                allow_redirects=False,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": user_agent},
            )
        except Exception as e:
            info(f"Error fetching redirected URL for {url}: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )
            return None

        location = (r.headers.get("Location") or "").strip()
        if location:
            next_url = urljoin(current_url, location)
            debug(f"Redirected from <d>{current_url}</d> to <d>{next_url}</d>")
            if "/404.html" in next_url:
                info(f"Link redirected to 404 page: <d>{next_url}</d>")
                return None
            if detect_crypter_type(next_url) is not None:
                return next_url
            if urlparse(next_url).netloc != source_netloc:
                return next_url
            current_url = next_url
            continue

        final_url = (r.url or current_url).strip()
        if "/404.html" in final_url:
            info(f"Link redirected to 404 page: <d>{final_url}</d>")
            return None
        if r.status_code >= 400:
            info(
                f"Error fetching redirected URL for {url}: HTTP {r.status_code} at {final_url}"
            )
            mark_hostname_issue(
                Source.initials,
                "download",
                f"HTTP {r.status_code} while resolving redirect",
            )
            return None
        info(
            f"Blocked attempt to resolve {url}. Your IP may be banned. Try again later."
        )
        return None

    debug(f"FF redirect hop limit exceeded for {url}")
    return None


def _mirror_from_url(url):
    host = urlparse(url).netloc.lower()
    if not host:
        return "direct"
    labels = host.split(".")
    return labels[-2] if len(labels) >= 2 else labels[0]
