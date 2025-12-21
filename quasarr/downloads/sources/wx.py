# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug

hostname = "wx"


def extract_links_from_content(content, host):
    """
    Extract download links from content (HTML or API data).
    Only filecrypt and hide are supported - other link crypters will cause an error.
    """
    links = []

    # If content is a string (HTML), parse it
    if isinstance(content, str):
        soup = BeautifulSoup(content, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link.get('href')

            # Skip internal links
            if href.startswith('/') or host in href:
                continue

            # Check supported links
            if re.search(r'filecrypt\.', href, re.IGNORECASE):
                if [href, "filecrypt"] not in links:
                    links.append([href, "filecrypt"])
            elif re.search(r'hide\.', href, re.IGNORECASE):
                if [href, "hide"] not in links:
                    links.append([href, "hide"])
            else:
                info(f"Unsupported link crypter/hoster found: {href}")
                debug(f"Currently only filecrypt and hide are supported. Other crypters may be added later.")

    # If content is API data (dict), extract from downloads or links
    elif isinstance(content, dict):
        link_sources = []
        if 'downloads' in content:
            link_sources = [d.get('url') or d.get('link') for d in content['downloads'] if
                            d.get('url') or d.get('link')]
        elif 'links' in content:
            link_sources = [item if isinstance(item, str) else item.get('url') for item in content['links'] if item]

        for link in link_sources:
            if re.search(r'filecrypt\.', link, re.IGNORECASE):
                if [link, "filecrypt"] not in links:
                    links.append([link, "filecrypt"])
            elif re.search(r'hide\.', link, re.IGNORECASE):
                if [link, "hide"] not in links:
                    links.append([link, "hide"])
            else:
                info(f"Unsupported link from API: {link}")

    return links


def get_wx_download_links(shared_state, url, mirror, title):
    """
    Get download links from a detail page.

    Returns:
        list of [url, hostname] pairs (same signature as other download link functions)
    """
    host = shared_state.values["config"]("Hostnames").get(hostname)

    headers = {
        'User-Agent': shared_state.values["user_agent"],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            info(f"{hostname.upper()}: Failed to load page: {url} (Status: {response.status_code})")
            return []

        # Extract slug from URL and try API first
        slug_match = re.search(r'/detail/([^/]+)', url)
        if slug_match:
            api_url = f'https://api.{host}/release/{slug_match.group(1)}'
            try:
                api_response = requests.get(api_url, headers={'User-Agent': shared_state.values["user_agent"]},
                                            timeout=10)
                if api_response.status_code == 200:
                    links = extract_links_from_content(api_response.json(), host)
                    if links:
                        debug(f"{hostname.upper()}: Found {len(links)} download link(s) via API for: {title}")
                        return links
            except:
                pass

        # Fall back to HTML parsing
        links = extract_links_from_content(response.text, host)

        if not links:
            info(f"{hostname.upper()}: No supported download links found on page: {url}")
            return []

        debug(f"{hostname.upper()}: Found {len(links)} download link(s) for: {title}")
        return links

    except Exception as e:
        info(f"{hostname.upper()}: Error extracting download links from {url}: {e}")
        return []
