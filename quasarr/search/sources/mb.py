# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import mark_hostname_issue, clear_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "mb"
supported_mirrors = ["rapidgator", "ddownload"]
XXX_REGEX = re.compile(r"\.xxx\.", re.I)
RESOLUTION_REGEX = re.compile(r"\d{3,4}p", re.I)
CODEC_REGEX = re.compile(r"x264|x265|h264|h265|hevc|avc", re.I)
IMDB_REGEX = re.compile(r"imdb\.com/title/(tt\d+)")

# map German month names to numbers
GERMAN_MONTHS = {
    'Januar': '01', 'Februar': '02', 'März': '03', 'April': '04', 'Mai': '05', 'Juni': '06',
    'Juli': '07', 'August': '08', 'September': '09', 'Oktober': '10', 'November': '11', 'Dezember': '12'
}


def convert_to_rss_date(date_str):
    parsed = datetime.strptime(date_str, "%d.%m.%Y - %H:%M")
    return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")


def extract_size(text):
    m = re.match(r"(\d+(?:\.\d+)?)\s*([A-Za-z]+)", text)
    if not m:
        raise ValueError(f"Invalid size format: {text!r}")
    return {"size": m.group(1), "sizeunit": m.group(2)}


def _parse_posts(soup, shared_state, password, mirror_filter,
                 is_search=False, request_from=None, search_string=None,
                 season=None, episode=None):
    releases = []
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

    for post in soup.select("div.post"):
        try:
            # title & source
            h1 = post.find("h1")
            a = h1.find("a")
            source = a["href"].strip()
            title = a.get_text(strip=True)

            # parse date
            date_p = post.find("p", class_="date_x")
            date_txt = date_p.get_text(strip=True) if date_p else None
            published = one_hour_ago
            if date_txt:
                m_date = re.search(r'(?:\w+, )?(\d{1,2})\.\s*(\w+)\s+(\d{4})\s+(\d{2}:\d{2})', date_txt)
                if m_date:
                    day, mon_name, year, hm = m_date.groups()
                    mon = GERMAN_MONTHS.get(mon_name, '01')
                    dt_obj = datetime.strptime(f"{day}.{mon}.{year} {hm}", "%d.%m.%Y %H:%M")
                    published = dt_obj.strftime("%a, %d %b %Y %H:%M:%S +0000")

            if is_search:
                if not shared_state.is_valid_release(title,
                                                     request_from,
                                                     search_string,
                                                     season,
                                                     episode):
                    continue

                # drop .XXX. unless user explicitly searched xxx
                if XXX_REGEX.search(title) and 'xxx' not in search_string.lower():
                    continue
                # require resolution/codec
                if not (RESOLUTION_REGEX.search(title) or CODEC_REGEX.search(title)):
                    continue
                # require no spaces in title
                if " " in title:
                    continue

                # can't check for mirrors in search context
                if mirror_filter and mirror_filter not in supported_mirrors:
                    continue
            else:
                mirror_candidates = []
                for strong in post.find_all('strong', string=re.compile(r'^Download', re.I)):
                    link_tag = strong.find_next_sibling('a')
                    if link_tag and link_tag.get_text(strip=True):
                        host = link_tag.get_text(strip=True).split('.')[0].lower()
                        mirror_candidates.append(host)
                valid = [m for m in mirror_candidates if m in supported_mirrors]
                if not valid or (mirror_filter and mirror_filter not in valid):
                    continue

            # extract IMDb ID
            imdb_id = None
            for tag in post.find_all('a', href=True):
                m = IMDB_REGEX.search(tag['href'])
                if m:
                    imdb_id = m.group(1)
                    break

            # size extraction
            mb = size_bytes = 0
            size_match = re.search(r"Größe:\s*([\d\.]+)\s*([GMK]B)", post.get_text())
            if size_match:
                sz = {"size": size_match.group(1), "sizeunit": size_match.group(2)}
                mb = shared_state.convert_to_mb(sz)
                size_bytes = mb * 1024 * 1024

            payload = urlsafe_b64encode(
                f"{title}|{source}|{mirror_filter}|{mb}|{password}|{imdb_id}|{hostname}".encode()
            ).decode()
            link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

            releases.append({
                "details": {
                    "title": title,
                    "hostname": hostname,
                    "imdb_id": imdb_id,
                    "link": link,
                    "mirror": mirror_filter,
                    "size": size_bytes,
                    "date": published,
                    "source": source
                },
                "type": "protected"
            })
        except Exception as e:
            debug(f"Error parsing {hostname.upper()} post: {e}")
            continue
    return releases


def mb_feed(shared_state, start_time, request_from, mirror=None):
    mb = shared_state.values["config"]("Hostnames").get(hostname)

    if not "arr" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return []

    password = mb
    section = "neuerscheinungen" if "Radarr" in request_from else "serie"
    url = f"https://{mb}/category/{section}/"
    headers = {'User-Agent': shared_state.values["user_agent"]}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        releases = _parse_posts(soup, shared_state, password, mirror_filter=mirror)
    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")
        mark_hostname_issue(hostname, "feed", str(e) if "e" in dir() else "Error occurred")
        releases = []
    debug(f"Time taken: {time.time() - start_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases


def mb_search(shared_state, start_time, request_from, search_string, mirror=None, season=None, episode=None):
    mb = shared_state.values["config"]("Hostnames").get(hostname)

    if not "arr" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return []

    password = mb
    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        title = get_localized_title(shared_state, imdb_id, 'de')
        if not title:
            info(f"Could not extract title from IMDb-ID {imdb_id}")
            return []
        search_string = html.unescape(title)

    q = quote_plus(search_string)
    url = f"https://{mb}/?s={q}&id=20&post_type=post"
    headers = {'User-Agent': shared_state.values["user_agent"]}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        releases = _parse_posts(
            soup, shared_state, password, mirror_filter=mirror,
            is_search=True, request_from=request_from,
            search_string=search_string, season=season, episode=episode
        )
    except Exception as e:
        info(f"Error loading {hostname.upper()} search: {e}")
        mark_hostname_issue(hostname, "search", str(e) if "e" in dir() else "Error occurred")
        releases = []
    debug(f"Time taken: {time.time() - start_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases
