# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import urlparse

import requests

from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import info
from quasarr.providers.sessions.nx import retrieve_and_validate_session

hostname = "nx"


def derive_mirror_from_url(url):
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


def get_filer_folder_links_via_api(shared_state, url):
    try:
        headers = {"User-Agent": shared_state.values["user_agent"], "Referer": url}

        m = re.search(r"/folder/([A-Za-z0-9]+)", url)
        if not m:
            return url

        folder_hash = m.group(1)
        api_url = f"https://filer.net/api/folder/{folder_hash}"

        r = requests.get(api_url, headers=headers, timeout=10)
        r.raise_for_status()

        data = r.json()
        files = data.get("files", [])
        links = []

        for f in files:
            file_hash = f.get("hash")
            if not file_hash:
                continue
            dl_url = f"https://filer.net/get/{file_hash}"
            links.append(dl_url)

        return links if links else url

    except:
        return url


def get_nx_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    NX source handler - auto-decrypts via site API and returns plain download links.
    """

    nx = shared_state.values["config"]("Hostnames").get("nx")

    if f"{nx}/release/" not in url:
        info("Link is not a Release link, could not proceed:" + url)

    nx_session = retrieve_and_validate_session(shared_state)
    if not nx_session:
        info(f"Could not retrieve valid session for {nx}")
        mark_hostname_issue(hostname, "download", "Session error")
        return {"links": []}

    headers = {"User-Agent": shared_state.values["user_agent"], "Referer": url}

    json_data = {}

    url_segments = url.split("/")
    payload_url = "/".join(url_segments[:-2]) + "/api/getLinks/" + url_segments[-1]

    try:
        r = nx_session.post(payload_url, headers=headers, json=json_data, timeout=10)
        r.raise_for_status()

        payload = r.json()
    except Exception as e:
        info(f"Could not get NX Links: {e}")
        mark_hostname_issue(hostname, "download", str(e))
        return {"links": []}

    if payload and any(key in payload for key in ("err", "error")):
        error_msg = payload.get("err") or payload.get("error")
        info(f"Error decrypting {title!r} URL: {url!r} - {error_msg}")
        mark_hostname_issue(hostname, "download", "Download error")
        shared_state.values["database"]("sessions").delete("nx")
        return {"links": []}

    try:
        decrypted_url = payload["link"][0]["url"]
        if decrypted_url:
            if "filer.net/folder/" in decrypted_url:
                urls = get_filer_folder_links_via_api(shared_state, decrypted_url)
            else:
                urls = [decrypted_url]

            # Convert to [[url, mirror], ...] format
            links = [[u, derive_mirror_from_url(u)] for u in urls]
            return {"links": links}
    except:
        pass

    info("Something went wrong decrypting " + str(title) + " URL: " + str(url))
    shared_state.values["database"]("sessions").delete("nx")
    return {"links": []}
