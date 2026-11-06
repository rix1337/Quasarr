# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import concurrent.futures
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import detect_crypter_type


def _extract_link_hoster_label(link):
    labels = []

    text = link.get_text(" ", strip=True)
    if text:
        labels.append(text)

    for image in link.find_all("img"):
        for attr in ("title", "alt", "src"):
            value = (image.get(attr) or "").strip()
            if value:
                labels.append(value)

    deduped = []
    seen = set()
    for label in labels:
        normalized = label.strip().replace(" ", "")
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            deduped.append(normalized)

    return " ".join(deduped)


def _direct_hoster_from_url(url):
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


class Source(AbstractDownloadSource):
    initials = "by"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        BY source handler - fetches protected download links from BY iframes.
        """
        by = shared_state.values["config"]("Hostnames").get(Source.initials)
        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        mirrors_lower = [m.lower() for m in mirrors] if mirrors else []
        links = []

        try:
            r = requests.get(
                url,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            frames = [
                iframe.get("src")
                for iframe in soup.find_all("iframe")
                if iframe.get("src")
            ]

            frame_urls = [src for src in frames if f"https://{by}" in src]
            if not frame_urls:
                debug(f"No iframe hosts found on {url} for {title}.")
                return {"links": []}

            async_results = []

            def fetch(url):
                try:
                    rq = requests.get(
                        url,
                        headers=headers,
                        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                    )
                    rq.raise_for_status()
                    return rq.text, url
                except Exception as e:
                    info(f"Error fetching iframe URL: {url}")
                    mark_hostname_issue(Source.initials, "download", str(e))
                    return None, url

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_url = {executor.submit(fetch, url): url for url in frame_urls}
                for future in concurrent.futures.as_completed(future_to_url):
                    content, source = future.result()
                    if content:
                        async_results.append((content, source))

            url_hosters = []
            for content, _source in async_results:
                host_soup = BeautifulSoup(content, "html.parser")
                link = host_soup.find(
                    "a",
                    href=re.compile(
                        r"https?://(?:www\.)?(?:hide\.cx|filecrypt\.(?:cc|co|to))/container/"
                    ),
                )

                # Fallback to the old format
                if not link:
                    link = host_soup.find("a", href=re.compile(r"/go\.php\?"))

                if not link:
                    continue

                href = link["href"]
                link_hostname = _extract_link_hoster_label(link)
                hostname_lower = link_hostname.lower()

                if mirrors_lower and not any(
                    m in hostname_lower for m in mirrors_lower
                ):
                    debug(
                        f'Skipping link from "{link_hostname}" (not in desired mirrors "{mirrors}")!'
                    )
                    continue

                url_hosters.append((href, link_hostname))

            def _is_protected_or_auto_link(candidate_url):
                return detect_crypter_type(candidate_url) in {
                    "filecrypt",
                    "hide",
                    "tolink",
                    "keeplinks",
                }

            def resolve_redirect(href_hostname):
                href, _hostname = href_hostname
                current_url = href
                visited = set()
                session = requests.Session()

                # If iframe already gives protected/auto URL, return directly.
                if _is_protected_or_auto_link(current_url):
                    return current_url

                for _hop in range(8):
                    if current_url in visited:
                        debug(f"BY redirect loop detected for {current_url}")
                        return None
                    visited.add(current_url)

                    if _is_protected_or_auto_link(current_url):
                        return current_url

                    try:
                        # Resolve redirect chain manually so we can capture final
                        # FileCrypt URL without requesting FileCrypt itself.
                        rq = session.get(
                            current_url,
                            headers=headers,
                            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                            allow_redirects=False,
                        )
                    except Exception as e:
                        debug(f"Error resolving BY redirect for {current_url}: {e}")
                        return None

                    location = (rq.headers.get("Location") or "").strip()
                    if location:
                        next_url = urljoin(current_url, location)
                        if "/404.html" in next_url:
                            debug(f"BY redirect led to 404 page: {next_url}")
                            return None
                        current_url = next_url
                        continue

                    final_url = (rq.url or current_url).strip()
                    if _is_protected_or_auto_link(final_url):
                        return final_url

                    if "/404.html" in final_url:
                        debug(f"BY redirect led to 404 page: {final_url}")
                        return None

                    if rq.status_code >= 400:
                        debug(
                            f"Error resolving BY redirect: HTTP {rq.status_code} at {final_url}"
                        )
                        return None

                    time.sleep(1)
                    return final_url

                debug(f"BY redirect hop limit exceeded for {href}")
                return None

            for pair in url_hosters:
                resolved_url = resolve_redirect(pair)
                link_hostname = pair[1]

                if not resolved_url:
                    continue

                # Protected/auto links must be returned as-is so downstream
                # classification stores them in CAPTCHA flow instead of direct.
                if _is_protected_or_auto_link(resolved_url):
                    links.append([resolved_url, "filecrypt"])
                    continue

                resolved_hostname = _direct_hoster_from_url(resolved_url)
                if resolved_hostname:
                    link_hostname = resolved_hostname

                if link_hostname and link_hostname.startswith(
                    ("ddownload", "rapidgator", "turbobit", "filecrypt")
                ):
                    if "rapidgator" in link_hostname:
                        links.insert(0, [resolved_url, link_hostname])
                    else:
                        links.append([resolved_url, link_hostname])

        except Exception as e:
            info(f"Error loading download links: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )

        return {"links": links}
