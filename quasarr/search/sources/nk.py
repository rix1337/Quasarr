# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "nk"
supported_mirrors = ["rapidgator", "ddownload"]


def convert_to_rss_date(date_str: str) -> str:
    date_str = date_str.strip()
    for fmt in ("%d. %B %Y / %H:%M", "%d.%m.%Y / %H:%M", "%d.%m.%Y - %H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            continue
    return ""


def extract_size(text: str) -> dict:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*([A-Za-z]+)", text)
    if match:
        size = match.group(1).replace(',', '.')
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}
    return {"size": "0", "sizeunit": "MB"}


def get_release_field(res, label):
    for li in res.select('ul.release-infos li'):
        sp = li.find('span')
        if not sp:
            return ''
        if sp.get_text(strip=True).lower() == label.lower():
            txt = li.get_text(' ', strip=True)
            return txt[len(sp.get_text(strip=True)):].strip()
    return ''


def nk_feed(*args, **kwargs):
    return nk_search(*args, **kwargs)


def nk_search(shared_state, start_time, request_from, search_string="", mirror=None, season=None, episode=None):
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    if not "arr" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by {hostname}.')
        return releases

    source_search = ""
    if search_string != "":
        imdb_id = shared_state.is_imdb_id(search_string)
        if imdb_id:
            local_title = get_localized_title(shared_state, imdb_id, 'de')
            if not local_title:
                info(f"{hostname}: no title for IMDb {imdb_id}")
                return releases
            source_search = local_title
        else:
            return releases
        source_search = unescape(source_search)
    else:
        imdb_id = None

    url = f'https://{host}/search'
    headers = {"User-Agent": shared_state.values["user_agent"]}
    data = {"search": source_search}

    try:
        r = requests.post(url, headers=headers, data=data, timeout=20)
        soup = BeautifulSoup(r.content, 'html.parser')
        results = soup.find_all('div', class_='article-right')
    except Exception as e:
        info(f"{hostname}: search load error: {e}")
        return releases

    if not results:
        return releases

    for result in results:
        try:
            imdb_a = result.select_one('a.imdb')
            if imdb_a and imdb_a.get('href'):
                try:
                    release_imdb_id = re.search(r'tt\d+', imdb_a['href']).group()
                    if imdb_id:
                        if release_imdb_id != imdb_id:
                            debug(f"{hostname}: IMDb ID mismatch: expected {imdb_id}, found {release_imdb_id}")
                            continue
                except Exception:
                    debug(f"{hostname}: could not extract IMDb ID")
                    continue
            else:
                debug(f"{hostname}: could not extract IMDb ID")
                continue

            a = result.find('a', class_='release-details', href=True)
            if not a:
                continue

            sub_title = result.find('span', class_='subtitle')
            if sub_title:
                title = sub_title.get_text(strip=True)
            else:
                continue

            if not shared_state.is_valid_release(title, request_from, search_string, season, episode):
                continue

            source = urljoin(f'https://{host}', a['href'])

            mb = 0
            size_text = get_release_field(result, 'Größe')
            if size_text:
                size_item = extract_size(size_text)
                mb = shared_state.convert_to_mb(size_item)

            if season != "" and episode == "":
                mb = 0  # Size unknown for season packs

            size = mb * 1024 * 1024

            password = ''
            mirrors_p = result.find('p', class_='mirrors')
            if mirrors_p:
                strong = mirrors_p.find('strong')
                if strong and strong.get_text(strip=True).lower().startswith('passwort'):
                    nxt = strong.next_sibling
                    if nxt:
                        val = str(nxt).strip()
                        if val:
                            password = val.split()[0]

            date_text = ''
            p_meta = result.find('p', class_='meta')
            if p_meta:
                spans = p_meta.find_all('span')
                if len(spans) >= 2:
                    date_part = spans[0].get_text(strip=True)
                    time_part = spans[1].get_text(strip=True).replace('Uhr', '').strip()
                    date_text = f"{date_part} / {time_part}"

            published = convert_to_rss_date(date_text) if date_text else ""

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
            info(e)
            debug(f"{hostname}: error parsing search result: {e}")
            continue

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")
    return releases
