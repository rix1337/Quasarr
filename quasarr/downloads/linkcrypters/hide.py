# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

import requests

from quasarr.providers.log import debug, info
from quasarr.providers.statistics import StatsHelper


def unhide_links(shared_state, url, session):
    try:
        links = []

        # Support both formats:
        # - https://hide.cx/container/{id}
        # - https://hide.cx/fc/Container/{id}.html
        match = re.search(
            r"/(?:fc/)?container/([a-z0-9A-Z\-]+)(?:\.html)?",
            url,
            re.IGNORECASE,
        )

        if not match:
            info(f"Invalid hide.cx URL: {url}")
            return []

        container_id = match.group(1)
        is_fc = "/fc/" in url.lower()
        # resolve fc foreign ID to canonical container ID
        if is_fc:
            headers = {
                "User-Agent": shared_state.values["user_agent"],
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            }

            info(f"Resolving hide.cx foreign container ID: {container_id}")
            resolve_url = f"https://api.hide.cx/fc/Container/{container_id}"
            resp = session.get(resolve_url, headers=headers, timeout=30)

            try:
                resolved = resp.json()
            except Exception:
                debug(f"Failed to resolve foreign container {container_id}")
                return []

            canonical_id = resolved.get("id")
            if not canonical_id:
                debug(f"No canonical container ID found for {container_id}")
                return []

            container_id = canonical_id
            debug(f"Resolved to canonical container ID: {container_id}")

        headers = {"User-Agent": shared_state.values["user_agent"]}
        info(f"Fetching hide.cx container with ID: {container_id}")

        headers = {"User-Agent": shared_state.values["user_agent"]}

        container_url = f"https://api.hide.cx/containers/{container_id}"
        response = session.get(container_url, headers=headers)
        data = response.json()

        link_ids = [link.get("id") for link in data.get("links", []) if link.get("id")]

        if not link_ids:
            debug(f"No link IDs found in container {container_id}")
            return []

        def fetch_link(link_id):
            debug(f"Fetching hide.cx link with ID: {link_id}")
            link_url = f"https://api.hide.cx/containers/{container_id}/links/{link_id}"
            link_data = session.get(link_url, headers=headers).json()
            return link_data.get("url")

        # Process links in batches of 10
        batch_size = 10
        for i in range(0, len(link_ids), batch_size):
            batch = link_ids[i : i + batch_size]
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = [executor.submit(fetch_link, link_id) for link_id in batch]
                for future in as_completed(futures):
                    try:
                        final_url = future.result()
                        if final_url and final_url not in links:
                            links.append(final_url)
                    except Exception as e:
                        info(f"Error fetching link: {e}")

        success = bool(links)
        if success:
            StatsHelper(shared_state).increment_captcha_decryptions_automatic()
        else:
            StatsHelper(shared_state).increment_failed_decryptions_automatic()

        return links
    except Exception as e:
        info(f"Error fetching hide.cx links: {e}")
        StatsHelper(shared_state).increment_failed_decryptions_automatic()
        return []


def decrypt_links_if_hide(shared_state: Any, items: List[List[str]]) -> Dict[str, Any]:
    """
    Resolve redirects and decrypt hide.cx links from a list of item lists.

    Each item list must include:
      - index 0: the URL to resolve
      - any additional metadata at subsequent indices (ignored here)

    :param shared_state: State object required by unhide_links function
    :param items: List of lists, where each inner list has the URL at index 0
    :return: Dict with 'status' and 'results' (flat list of decrypted link URLs)
    """
    if not items:
        info("No items provided to decrypt.")
        return {"status": "error", "results": []}

    session = requests.Session()
    session.max_redirects = 5

    hide_urls: List[str] = []
    for item in items:
        original_url = item[0]
        if not original_url:
            debug(f"Skipping item without URL: {item}")
            continue

        try:
            # Try HEAD first, fallback to GET
            try:
                resp = session.head(original_url, allow_redirects=True, timeout=10)
            except requests.RequestException:
                resp = session.get(original_url, allow_redirects=True, timeout=10)

            final_url = resp.url

            # accept hide.cx even if it did not redirect
            if "hide.cx" in final_url or "hide.cx" in original_url:
                debug(f"Identified hide.cx link: {final_url}")
                hide_urls.append(final_url)
            else:
                debug(f"Not a hide.cx link (skipped): {final_url}")

        except requests.RequestException as e:
            info(f"Error resolving URL {original_url}: {e}")
            continue

    if not hide_urls:
        debug(f"No hide.cx links found among {len(items)} items.")
        return {"status": "none", "results": []}

    info(f"Found {len(hide_urls)} hide.cx URLs; decrypting...")
    decrypted_links: List[str] = []
    for url in hide_urls:
        try:
            links = unhide_links(shared_state, url, session)
            if not links:
                debug(f"No links decrypted for {url}")
                continue
            decrypted_links.extend(links)
        except Exception as e:
            info(f"Failed to decrypt {url}: {e}")
            continue

    if not decrypted_links:
        info(f"Could not decrypt any links from hide.cx URLs.")
        return {"status": "error", "results": []}

    return {"status": "success", "results": decrypted_links}
