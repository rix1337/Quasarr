# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests

from quasarr.providers.log import info, debug

hostname = "wx"


def get_wx_download_links(shared_state, url, mirror, title):
    """
    Get download links from API based on title and mirror.

    Returns:
        list of [url, hoster] pairs where hoster is the actual mirror (e.g., 'ddownload.com', 'rapidgator.net')
    """
    host = shared_state.values["config"]("Hostnames").get(hostname)

    headers = {
        'User-Agent': shared_state.values["user_agent"],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    try:
        session = requests.Session()

        # First, load the page to establish session cookies
        response = session.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            info(f"{hostname.upper()}: Failed to load page: {url} (Status: {response.status_code})")
            return []

        # Extract slug from URL
        slug_match = re.search(r'/detail/([^/]+)', url)
        if not slug_match:
            info(f"{hostname.upper()}: Could not extract slug from URL: {url}")
            return []

        api_url = f'https://api.{host}/start/d/{slug_match.group(1)}'

        # Update headers for API request
        api_headers = {
            'User-Agent': shared_state.values["user_agent"],
            'Accept': 'application/json'
        }

        debug(f"{hostname.upper()}: Fetching API data from: {api_url}")
        api_response = session.get(api_url, headers=api_headers, timeout=30)

        if api_response.status_code != 200:
            info(f"{hostname.upper()}: Failed to load API: {api_url} (Status: {api_response.status_code})")
            return []

        data = api_response.json()

        # Navigate to releases in the API response
        if 'item' not in data or 'releases' not in data['item']:
            info(f"{hostname.upper()}: No releases found in API response")
            return []

        releases = data['item']['releases']

        # Find the release matching the title
        matching_release = None
        for release in releases:
            if release.get('fulltitle') == title:
                matching_release = release
                break

        if not matching_release:
            info(f"{hostname.upper()}: No release found matching title: {title}")
            return []

        # Extract crypted_links based on mirror
        crypted_links = matching_release.get('crypted_links', {})

        if not crypted_links:
            info(f"{hostname.upper()}: No crypted_links found for: {title}")
            return []

        links = []

        # If mirror is specified, find matching hoster (handle partial matches like 'ddownload' -> 'ddownload.com')
        if mirror:
            matched_hoster = None
            for hoster in crypted_links.keys():
                if mirror.lower() in hoster.lower() or hoster.lower() in mirror.lower():
                    matched_hoster = hoster
                    break

            if matched_hoster:
                link = crypted_links[matched_hoster]
                # Prefer hide over filecrypt
                if re.search(r'hide\.', link, re.IGNORECASE):
                    links.append([link, matched_hoster])
                    debug(f"{hostname.upper()}: Found hide link for mirror {matched_hoster}")
                elif re.search(r'filecrypt\.', link, re.IGNORECASE):
                    links.append([link, matched_hoster])
                    debug(f"{hostname.upper()}: Found filecrypt link for mirror {matched_hoster}")
            else:
                info(
                    f"{hostname.upper()}: Mirror '{mirror}' not found in available hosters: {list(crypted_links.keys())}")
        else:
            # If no mirror specified, get all available crypted links (prefer hide over filecrypt)
            for hoster, link in crypted_links.items():
                if re.search(r'hide\.', link, re.IGNORECASE):
                    links.append([link, hoster])
                    debug(f"{hostname.upper()}: Found hide link for hoster {hoster}")
                elif re.search(r'filecrypt\.', link, re.IGNORECASE):
                    links.append([link, hoster])
                    debug(f"{hostname.upper()}: Found filecrypt link for hoster {hoster}")

        if not links:
            info(f"{hostname.upper()}: No supported crypted links found for: {title}")
            return []

        debug(f"{hostname.upper()}: Found {len(links)} crypted link(s) for: {title}")
        return links

    except Exception as e:
        info(f"{hostname.upper()}: Error extracting download links from {url}: {e}")
        return []
