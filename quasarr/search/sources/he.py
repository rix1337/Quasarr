# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta
from html import unescape

import requests
from bs4 import BeautifulSoup

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "he"
supported_mirrors = ["rapidgator", "nitroflare"]


def parse_posted_ago(txt):
    try:
        m = re.search(r"(\d+)\s*(sec|min|hour|day|week|month|year)s?", txt, re.IGNORECASE)
        if not m:
            return ''
        value = int(m.group(1))
        unit = m.group(2).lower()
        now = datetime.utcnow()
        if unit.startswith('sec'):
            delta = timedelta(seconds=value)
        elif unit.startswith('min'):
            delta = timedelta(minutes=value)
        elif unit.startswith('hour'):
            delta = timedelta(hours=value)
        elif unit.startswith('day'):
            delta = timedelta(days=value)
        elif unit.startswith('week'):
            delta = timedelta(weeks=value)
        elif unit.startswith('month'):
            delta = timedelta(days=30 * value)
        else:
            delta = timedelta(days=365 * value)
        return (datetime.utcnow() - delta).strftime("%a, %d %b %Y %H:%M:%S +0000")
    except Exception:
        return ''


def extract_size(text: str) -> dict:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*([A-Za-z]+)", text)
    if match:
        size = match.group(1).replace(',', '.')
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}
    return {"size": "0", "sizeunit": "MB"}


def he_feed(*args, **kwargs):
    return he_search(*args, **kwargs)


def he_search(shared_state, start_time, request_from, search_string="", mirror=None, season=None, episode=None):
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    if not "arr" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    if "radarr" in request_from.lower():
        tag = "movies"
    else:
        tag = "tv-shows"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by {hostname}.')
        return releases

    source_search = ""
    if search_string != "":
        imdb_id = shared_state.is_imdb_id(search_string)
        if imdb_id:
            local_title = get_localized_title(shared_state, imdb_id, 'en')
            if not local_title:
                info(f"{hostname}: no title for IMDb {imdb_id}")
                return releases
            source_search = local_title
        else:
            return releases
        source_search = unescape(source_search)
    else:
        imdb_id = None

    url = f'https://{host}/tag/{tag}/'

    headers = {"User-Agent": shared_state.values["user_agent"]}
    params = {"s": source_search}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        results = soup.find_all('div', class_='item')
    except Exception as e:
        info(f"{hostname}: search load error: {e}")
        return releases

    if not results:
        return releases

    for result in results:
        try:
            data = result.find('div', class_='data')
            if not data:
                continue

            headline = data.find('h5')
            if not headline:
                continue

            a = headline.find('a', href=True)
            if not a:
                continue

            source = a['href'].strip()

            head_title = a.get_text(strip=True)
            if not head_title:
                continue

            head_split = head_title.split(" – ")
            title = head_split[0].strip()

            if not shared_state.is_valid_release(title, request_from, search_string, season, episode):
                continue

            size_item = extract_size(head_split[1].strip())
            mb = shared_state.convert_to_mb(size_item)

            size = mb * 1024 * 1024

            published = None
            p_meta = data.find('p', class_='meta')
            if p_meta:
                posted_span = None
                for sp in p_meta.find_all('span'):
                    txt = sp.get_text(' ', strip=True)
                    if txt.lower().startswith('posted') or 'ago' in txt.lower():
                        posted_span = txt
                        break

                if posted_span:
                    published = parse_posted_ago(posted_span)

            if published is None:
                continue

            release_imdb_id = None
            try:
                r = requests.get(source, headers=headers, timeout=10)
                soup = BeautifulSoup(r.content, 'html.parser')
                imdb_link = soup.find('a', href=re.compile(r"imdb\.com/title/tt\d+", re.IGNORECASE))
                if imdb_link:
                    release_imdb_id = re.search(r'tt\d+', imdb_link['href']).group()
                    if imdb_id and release_imdb_id != imdb_id:
                        debug(f"{hostname}: IMDb ID mismatch: expected {imdb_id}, found {release_imdb_id}")
                        continue
                else:
                    debug(f"{hostname}: imdb link not found for title {title}")
            except Exception as e:
                debug(f"{hostname}: failed to determine imdb_id for title {title}")
                continue

            password = None
            payload = urlsafe_b64encode(
                f"{title}|{source}|{mirror}|{mb}|{password}|{release_imdb_id}".encode("utf-8")).decode()
            link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

            releases.append({
                "details": {
                    "title": title,
                    "hostname": hostname,
                    "imdb_id": release_imdb_id,
                    "link": link,
                    "mirror": mirror,
                    "size": size,
                    "date": published,
                    "source": source
                },
                "type": "protected"
            })
        except Exception as e:
            debug(f"{hostname}: error parsing search result: {e}")
            continue

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")
    return releases
