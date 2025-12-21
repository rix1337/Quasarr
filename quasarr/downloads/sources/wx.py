# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug

hostname = "wx"


def extract_links_from_page(page_html, host):
    """
    Extract download links from a detail page.
    Only filecrypt and hide are supported - other link crypters will cause an error.
    """
    links = []
    soup = BeautifulSoup(page_html, 'html.parser')
    
    for link in soup.find_all('a', href=True):
        href = link.get('href')
        
        # Skip internal links
        if href.startswith('/') or host in href:
            continue
        
        # ONLY support filecrypt and hide
        if re.search(r'filecrypt\.cc', href, re.IGNORECASE):
            if href not in links:
                links.append(href)
        elif re.search(r'hide\.', href, re.IGNORECASE):
            if href not in links:
                links.append(href)
        elif re.search(r'(linksnappy|relink\.us|links\.snahp|rapidgator|uploaded\.net|nitroflare|ddownload\.com|filefactory|katfile|mexashare|keep2share|mega\.nz|1fichier)', href, re.IGNORECASE):
            # These crypters/hosters are NOT supported yet
            info(f"Unsupported link crypter/hoster found: {href}")
            info(f"Currently only filecrypt.cc and hide.* are supported. Other crypters may be added later.")
    
    return links


def get_wx_download_links(shared_state, url, mirror, title):
    """
    Get download links from a detail page.
    
    Returns:
        dict with 'links', 'password', and 'title'
    """
    host = shared_state.values["config"]("Hostnames").get(hostname)
    
    import requests
    
    headers = {
        'User-Agent': shared_state.values["user_agent"],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            info(f"{hostname.upper()}: Failed to load page: {url} (Status: {response.status_code})")
            return {}
        
        # Extract slug from URL
        slug_match = re.search(r'/detail/([^/]+)', url)
        if slug_match:
            slug = slug_match.group(1)
            
            # Try to fetch via API
            api_url = f'https://api.{host}/release/{slug}'
            try:
                api_response = requests.get(api_url, headers={'User-Agent': shared_state.values["user_agent"]}, 
                                           timeout=10)
                if api_response.status_code == 200:
                    data = api_response.json()
                    
                    links = []
                    if 'downloads' in data:
                        for download in data['downloads']:
                            link = download.get('url') or download.get('link')
                            if link:
                                # Check if supported
                                if re.search(r'filecrypt\.cc|hide\.', link, re.IGNORECASE):
                                    links.append(link)
                                else:
                                    info(f"Unsupported link from API: {link}")
                    elif 'links' in data:
                        for link_item in data['links']:
                            link = link_item if isinstance(link_item, str) else link_item.get('url')
                            if link:
                                # Check if supported
                                if re.search(r'filecrypt\.cc|hide\.', link, re.IGNORECASE):
                                    links.append(link)
                                else:
                                    info(f"Unsupported link from API: {link}")
                    
                    if links:
                        password = f"www.{host}"
                        debug(f"{hostname.upper()}: Found {len(links)} download link(s) via API for: {title}")
                        
                        return {
                            "links": links,
                            "password": password,
                            "title": title
                        }
            except:
                pass
        
        # Fall back to HTML parsing
        links = extract_links_from_page(response.text, host)
        
        if not links:
            info(f"{hostname.upper()}: No supported download links found on page: {url}")
            return {}
        
        password = f"www.{host}"
        password_patterns = [
            r'(?:Passwort|Password|Pass|PW)[\s:]*([^\s<]+)',
        ]
        
        for pattern in password_patterns:
            match = re.search(pattern, response.text, re.IGNORECASE)
            if match and len(match.groups()) > 0:
                password = match.group(1)
                break
        
        debug(f"{hostname.upper()}: Found {len(links)} download link(s) for: {title}")
        
        return {
            "links": links,
            "password": password,
            "title": title
        }
        
    except Exception as e:
        info(f"{hostname.upper()}: Error extracting download links from {url}: {e}")
        return {}
