# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
from base64 import urlsafe_b64encode
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "sl"
supported_mirrors = ["nitroflare", "ddownload"]  # ignoring captcha-protected multiup/mirrorace for now


def extract_size(text):
    match = re.match(r"([\d\.]+)\s*([KMGT]B)", text, re.IGNORECASE)
    if match:
        size = match.group(1)
        unit = match.group(2).upper()
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def parse_pubdate_to_iso(pubdate_str):
    """
    Parse an RFC-822 pubDate from RSS into an ISO8601 string with timezone.
    """
    dt = datetime.datetime.strptime(pubdate_str, '%a, %d %b %Y %H:%M:%S %z')
    return dt.isoformat()


def sl_feed(shared_state, start_time, request_from, mirror=None):
    releases = []

    sl = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = sl

    if "lazylibrarian" in request_from.lower():
        feed_type = "ebooks"
    elif "radarr" in request_from.lower():
        feed_type = "movies"
    else:
        feed_type = "tv-shows"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported: {supported_mirrors}. Skipping!')
        return releases

    url = f'https://{sl}/{feed_type}/feed/'
    headers = {'User-Agent': shared_state.values['user_agent']}

    try:
        xml_text = requests.get(url, headers=headers, timeout=10).text
        root = ET.fromstring(xml_text)

        for item in root.find('channel').findall('item'):
            try:
                title = item.findtext('title').strip()
                if 'lazylibrarian' in request_from.lower():
                    # lazylibrarian can only detect specific date formats / issue numbering for magazines
                    title = shared_state.normalize_magazine_title(title)

                source = item.findtext('link').strip()

                desc = item.findtext('description') or ''

                size_match = re.search(r"Size:\s*([\d\.]+\s*(?:GB|MB|KB|TB))", desc, re.IGNORECASE)
                if not size_match:
                    debug(f"Size not found in RSS item: {title}")
                    continue
                size_info = size_match.group(1).strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item)
                size = mb * 1024 * 1024

                pubdate = item.findtext('pubDate').strip()
                published = parse_pubdate_to_iso(pubdate)

                m = re.search(r"https?://www\.imdb\.com/title/(tt\d+)", desc)
                imdb_id = m.group(1) if m else None

                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")
                ).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                releases.append({
                    "details": {
                        "title": title,
                        "hostname": hostname.lower(),
                        "imdb_id": imdb_id,
                        "link": link,
                        "mirror": mirror,
                        "size": size,
                        "date": published,
                        "source": source
                    },
                    "type": "protected"
                })

            except Exception as e:
                info(f"Error parsing {hostname.upper()} feed item: {e}")
                continue

    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")
    return releases


def sl_search(shared_state, start_time, request_from, search_string, mirror=None, season=None, episode=None):
    releases = []
    sl = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = sl

    if "lazylibrarian" in request_from.lower():
        feed_type = "ebooks"
    elif "radarr" in request_from.lower():
        feed_type = "movies"
    else:
        feed_type = "tv-shows"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported: {supported_mirrors}. Skipping!')
        return releases

    try:
        imdb_id = shared_state.is_imdb_id(search_string)
        if imdb_id:
            search_string = get_localized_title(shared_state, imdb_id, 'en') or ''
            search_string = html.unescape(search_string)
            if not search_string:
                info(f"Could not extract title from IMDb-ID {imdb_id}")
                return releases

        # Build the list of URLs to search. For tv-shows also search the "foreign" section.
        q = quote_plus(search_string)
        urls = [f'https://{sl}/{feed_type}/?s={q}']
        if feed_type == "tv-shows":
            urls.append(f'https://{sl}/foreign/?s={q}')

        headers = {"User-Agent": shared_state.values['user_agent']}

        # Fetch pages in parallel (so we don't double the slow site latency)
        def fetch(url):
            try:
                debug(f"Fetching {url} ({hostname})")
                r = requests.get(url, headers=headers, timeout=10)
                r.raise_for_status()
                return r.text
            except Exception as e:
                info(f"Error fetching {hostname} url {url}: {e}")
                return ''

        html_texts = []
        with ThreadPoolExecutor(max_workers=len(urls)) as tpe:
            futures = {tpe.submit(fetch, u): u for u in urls}
            for future in as_completed(futures):
                try:
                    html_texts.append(future.result())
                except Exception as e:
                    info(f"Error fetching {hostname} search page: {e}")

        # Parse each result and collect unique releases (dedupe by source link)
        seen_sources = set()
        for html_text in html_texts:
            if not html_text:
                continue
            try:
                soup = BeautifulSoup(html_text, 'html.parser')
                posts = soup.find_all('div', class_=lambda c: c and c.startswith('post-'))

                for post in posts:
                    try:
                        a = post.find('h1').find('a')
                        title = a.get_text(strip=True)

                        if not shared_state.is_valid_release(title,
                                                             request_from,
                                                             search_string,
                                                             season,
                                                             episode):
                            continue

                        if 'lazylibrarian' in request_from.lower():
                            title = shared_state.normalize_magazine_title(title)

                        source = a['href']
                        # dedupe
                        if source in seen_sources:
                            continue
                        seen_sources.add(source)

                        # Published date
                        time_tag = post.find('span', {'class': 'localtime'})
                        published = None
                        if time_tag and time_tag.has_attr('data-lttime'):
                            published = time_tag['data-lttime']
                        published = published or datetime.datetime.utcnow().isoformat() + '+00:00'

                        size = 0
                        imdb_id = None

                        payload = urlsafe_b64encode(
                            f"{title}|{source}|{mirror}|0|{password}|{imdb_id}".encode('utf-8')
                        ).decode('utf-8')
                        link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                        releases.append({
                            "details": {
                                "title": title,
                                "hostname": hostname.lower(),
                                "imdb_id": imdb_id,
                                "link": link,
                                "mirror": mirror,
                                "size": size,
                                "date": published,
                                "source": source
                            },
                            "type": "protected"
                        })
                    except Exception as e:
                        info(f"Error parsing {hostname.upper()} search item: {e}")
                        continue
            except Exception as e:
                info(f"Error parsing {hostname.upper()} search HTML: {e}")
                continue

    except Exception as e:
        info(f"Error loading {hostname.upper()} search page: {e}")

    elapsed = time.time() - start_time
    debug(f"Search time: {elapsed:.2f}s ({hostname})")
    return releases
