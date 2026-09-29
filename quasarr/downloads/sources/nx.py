# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import json
import re
from urllib.parse import urlparse

import requests

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import info
from quasarr.providers.sessions.nx import retrieve_and_validate_session


class Source(AbstractDownloadSource):
    initials = "nx"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        NX source handler - fetches release details via public API,
        decodes download tokens to get filer.net URLs.
        """
        requested_mirrors = {
            _normalize_mirror_name(mirror) for mirror in (mirrors or []) if mirror
        }
        if requested_mirrors and "filer" not in requested_mirrors:
            info(f"No requested mirrors are available for {title}")
            return {"links": []}

        nx = shared_state.values["config"]("Hostnames").get(Source.initials)

        if f"{nx}/release/" not in url:
            info("Link is not a Release link, could not proceed: " + url)
            return {"links": []}

        slug = url.split("/")[-1]
        if not slug:
            info(f"Could not extract release slug from URL: {url}")
            return {"links": []}

        nx_session = retrieve_and_validate_session(shared_state)
        if not nx_session:
            info(f"Could not retrieve valid session for {nx}")
            mark_hostname_issue(Source.initials, "download", "Session error")
            return {"links": []}

        headers = {"User-Agent": shared_state.values["user_agent"]}

        try:
            r = nx_session.get(
                f"https://{nx}/api/releases/{slug}",
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            release_data = r.json()
        except Exception as e:
            info(f"Could not get release details: {e}")
            mark_hostname_issue(Source.initials, "download", str(e))
            return {"links": []}

        links_data = release_data.get("links", [])
        if not links_data:
            info(f"No links found for release {slug}")
            return {"links": []}

        urls = []
        for link_entry in links_data:
            if link_entry.get("isOffline"):
                continue

            hoster = link_entry.get("hoster", "")
            if "filer" not in hoster.lower():
                info(f"Skipping non-filer hoster: {hoster}")
                continue

            download_token = link_entry.get("downloadToken")
            if not download_token:
                continue

            filer_hash = _decode_download_token(download_token)
            if not filer_hash:
                info(f"Could not decode download token for {title}")
                continue

            filer_base = _get_filer_base(hoster)
            filer_url = f"{filer_base}/get/{filer_hash}"
            urls.append(filer_url)

        if not urls:
            info(f"No valid filer URLs found for {title}")
            return {"links": []}

        result_links = []
        for u in urls:
            if _is_filer_folder_url(u):
                folder_urls = _get_filer_folder_links_via_api(shared_state, u)
                for fu in folder_urls:
                    result_links.append([fu, _derive_mirror_from_url(fu)])
            else:
                result_links.append([u, _derive_mirror_from_url(u)])

        return {"links": result_links}


def _derive_mirror_from_url(url):
    """Extract hoster name from URL hostname."""
    try:
        hostname = urlparse(url).netloc.lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        parts = hostname.split(".")
        if len(parts) >= 2:
            return parts[-2]
        return hostname
    except:
        return "unknown"


def _decode_download_token(token):
    """Decode a download token to extract the filer hash slug."""
    try:
        payload_part = token.split(".")[0]
        padded = payload_part + "=" * (4 - len(payload_part) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        data = json.loads(decoded)
        return data.get("slug")
    except Exception:
        return None


def _get_filer_base(hoster):
    """Derive the filer base URL from the hoster name."""
    hoster_lower = hoster.lower().strip()
    if "://" in hoster_lower:
        parsed = urlparse(hoster_lower)
        return f"{parsed.scheme}://{parsed.netloc}"
    if "." in hoster_lower:
        return f"https://{hoster_lower}"
    return f"https://{hoster_lower}.net"


def _normalize_mirror_name(mirror_name):
    normalized = mirror_name.lower().strip()

    if "://" in normalized:
        parsed = urlparse(normalized)
        normalized = parsed.netloc or parsed.path

    if normalized.startswith("www."):
        normalized = normalized[4:]

    normalized = normalized.split("/", 1)[0]
    normalized = normalized.split(":", 1)[0]
    if " " in normalized:
        normalized = normalized.split()[-1]
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]

    aliases = {
        "filernet": "filer",
    }
    return aliases.get(normalized, normalized)


def _is_filer_url(url):
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        provider = host.split(".", 1)[0]
        return provider == "filer"
    except Exception:
        return False


def _is_filer_folder_url(url):
    try:
        parsed = urlparse(url)
        return _is_filer_url(url) and "/folder/" in parsed.path
    except Exception:
        return False


def _get_filer_folder_links_via_api(shared_state, url):
    try:
        headers = {"User-Agent": shared_state.values["user_agent"], "Referer": url}
        parsed = urlparse(url)
        api_base = f"{parsed.scheme}://{parsed.netloc}"

        m = re.search(r"/folder/([A-Za-z0-9]+)", url)
        if not m:
            return [url]

        folder_hash = m.group(1)
        api_url = f"{api_base}/api/folder/{folder_hash}"

        r = requests.get(
            api_url,
            headers=headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        r.raise_for_status()

        data = r.json()
        files = data.get("files", [])
        links = []

        for f in files:
            file_hash = f.get("hash")
            if not file_hash:
                continue
            dl_url = f"{api_base}/get/{file_hash}"
            links.append(dl_url)

        return links if links else [url]

    except:
        return [url]
