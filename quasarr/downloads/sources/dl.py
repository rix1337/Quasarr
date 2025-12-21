# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug
from quasarr.providers.sessions.dl import retrieve_and_validate_session, fetch_via_requests_session, invalidate_session

hostname = "dl"


def extract_password_from_post(soup, host):
    """
    Extract password from forum post using multiple strategies.
    Returns empty string if no password found or if explicitly marked as 'no password'.
    """
    # Get flattened text from the post - collapse whitespace to single spaces
    post_text = soup.get_text()
    post_text = re.sub(r'\s+', ' ', post_text).strip()

    # Strategy 1: Look for password label followed by the password value
    # Pattern: "Passwort:" followed by optional separators, then the password
    password_pattern = r'(?:passwort|password|pass|pw)[\s:]+([a-zA-Z0-9._-]{2,50})'
    match = re.search(password_pattern, post_text, re.IGNORECASE)

    if match:
        password = match.group(1).strip()
        # Skip if it looks like a section header or common word
        if not re.match(r'^(?:download|mirror|link|episode|info|mediainfo|spoiler|hier|click|klick|kein|none|no)',
                        password, re.IGNORECASE):
            debug(f"Found password: {password}")
            return password

    # Strategy 2: Look for explicit "no password" indicators (only if no valid password found)
    no_password_patterns = [
        r'(?:passwort|password|pass|pw)[\s:]*(?:kein|none|no|nicht|not|nein|-|–|—)',
        r'(?:kein|none|no|nicht|not|nein)\s*(?:passwort|password|pass|pw)',
    ]

    for pattern in no_password_patterns:
        if re.search(pattern, post_text, re.IGNORECASE):
            debug("No password required (explicitly stated)")
            return ""

    # Strategy 3: Default to hostname-based password
    default_password = f"www.{host}"
    debug(f"No password found, using default: {default_password}")
    return default_password


def extract_links_and_password_from_post(post_content, host):
    """
    Extract download links and password from a forum post.
    Only filecrypt and hide are supported - other link crypters will cause an error.

    Returns:
        tuple of (links, password) where:
        - links: list of [url, hostname] pairs
        - password: extracted password string
    """
    links = []
    soup = BeautifulSoup(post_content, 'html.parser')

    for link in soup.find_all('a', href=True):
        href = link.get('href')

        # Skip internal forum links
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
            debug(f"Unsupported link crypter/hoster found: {href}")
            debug(f"Currently only filecrypt and hide are supported. Other crypters may be added later.")

    # Only extract password if we found links
    password = ""
    if links:
        password = extract_password_from_post(soup, host)

    return links, password


def get_dl_download_links(shared_state, url, mirror, title):
    """
    Get download links from a thread.

    Returns:
        tuple of (links, password) where:
        - links: list of [url, hostname] pairs
        - password: extracted password string
    """
    host = shared_state.values["config"]("Hostnames").get(hostname)

    sess = retrieve_and_validate_session(shared_state)
    if not sess:
        info(f"Could not retrieve valid session for {host}")
        return [], ""

    try:
        response = fetch_via_requests_session(shared_state, method="GET", target_url=url, timeout=30)

        if response.status_code != 200:
            info(f"Failed to load thread page: {url} (Status: {response.status_code})")
            return [], ""

        soup = BeautifulSoup(response.text, 'html.parser')

        first_post = soup.select_one('article.message--post')
        if not first_post:
            info(f"Could not find first post in thread: {url}")
            return [], ""

        post_content = first_post.select_one('div.bbWrapper')
        if not post_content:
            info(f"Could not find post content in thread: {url}")
            return [], ""

        # Extract both links and password from the same post content
        links, password = extract_links_and_password_from_post(str(post_content), host)

        if not links:
            info(f"No supported download links found in thread: {url}")
            return [], ""

        debug(f"Found {len(links)} download link(s) for: {title} (password: {password})")
        return links, password

    except Exception as e:
        info(f"Error extracting download links from {url}: {e}")
        invalidate_session(shared_state)
        return [], ""
