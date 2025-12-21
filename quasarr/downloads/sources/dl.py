# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug
from quasarr.providers.sessions.dl import retrieve_and_validate_session, fetch_via_requests_session, invalidate_session

hostname = "dl"


def extract_links_from_post(post_html, host):
    """
    Extract download links from a forum post.
    Only filecrypt and hide are supported - other link crypters will cause an error.
    """
    links = []
    soup = BeautifulSoup(post_html, 'html.parser')
    
    for link in soup.find_all('a', href=True):
        href = link.get('href')
        
        # Skip internal forum links
        if href.startswith('/') or host in href:
            continue
        
        # ONLY support filecrypt and hide
        if re.search(r'filecrypt\.cc', href, re.IGNORECASE):
            if href not in links:
                links.append(href)
        elif re.search(r'hide\.', href, re.IGNORECASE):
            if href not in links:
                links.append(href)
        elif re.search(r'(linksnappy|relink\.us|links\.snahp|rapidgator|uploaded\.net|nitroflare|turbobit|ddownload\.com|filefactory|katfile|mexashare|keep2share|alfafile|mega\.nz|1fichier)', href, re.IGNORECASE):
            # These crypters/hosters are NOT supported yet
            info(f"Unsupported link crypter/hoster found: {href}")
            info(f"Currently only filecrypt.cc and hide.* are supported. Other crypters may be added later.")
    
    return links


def get_dl_download_links(shared_state, url, mirror, title):
    """
    Get download links from a thread.
    
    Returns:
        dict with 'links', 'password', and 'title'
    """
    host = shared_state.values["config"]("Hostnames").get(hostname)
    
    sess = retrieve_and_validate_session(shared_state)
    if not sess:
        info(f"Could not retrieve valid session for {host}")
        return {}

    try:
        response = fetch_via_requests_session(shared_state, method="GET", 
                                             target_url=url, 
                                             timeout=30)
        
        if response.status_code != 200:
            info(f"Failed to load thread page: {url} (Status: {response.status_code})")
            return {}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        first_post = soup.select_one('article.message--post')
        if not first_post:
            info(f"Could not find first post in thread: {url}")
            return {}
        
        post_content = first_post.select_one('div.bbWrapper')
        if not post_content:
            info(f"Could not find post content in thread: {url}")
            return {}
        
        links = extract_links_from_post(str(post_content), host)
        
        if not links:
            info(f"No supported download links found in thread: {url}")
            return {}
        
        password = f"www.{host}"
        password_patterns = [
            r'(?:Passwort|Password|Pass|PW)[\s:]*([^\s<]+)',
        ]
        
        post_text = post_content.get_text()
        for pattern in password_patterns:
            match = re.search(pattern, post_text, re.IGNORECASE)
            if match and len(match.groups()) > 0:
                password = match.group(1)
                break
        
        debug(f"Found {len(links)} download link(s) for: {title}")
        
        return {
            "links": links,
            "password": password,
            "title": title
        }
        
    except Exception as e:
        info(f"Error extracting download links from {url}: {e}")
        invalidate_session(shared_state)
        return {}
