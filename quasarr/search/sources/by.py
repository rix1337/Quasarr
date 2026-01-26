# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info

hostname = "by"
supported_mirrors = ["rapidgator", "ddownload", "nitroflare"]

RESOLUTION_REGEX = re.compile(r"\d{3,4}p", re.I)
CODEC_REGEX = re.compile(r"x264|x265|h264|h265|hevc|avc", re.I)
XXX_REGEX = re.compile(r"\.xxx\.", re.I)
IMDB_REGEX = re.compile(r"imdb\.com/title/(tt\d+)")


def convert_to_rss_date(date_str):
    """
    BY date format: 'dd.mm.yy HH:MM', e.g. '20.07.25 17:48'
    """
    dt_obj = datetime.strptime(date_str, "%d.%m.%y %H:%M")
    return dt_obj.strftime("%a, %d %b %Y %H:%M:%S +0000")


def extract_size(text):
    m = re.match(r"(\d+(?:[.,]\d+)?)\s*([A-Za-z]+)", text)
    if not m:
        raise ValueError(f"Invalid size format: {text!r}")
    size_str = m.group(1).replace(",", ".")
    sizeunit = m.group(2)
    size_float = float(size_str)  # convert to float here
    return {"size": size_float, "sizeunit": sizeunit}


def _parse_posts(
    soup,
    shared_state,
    base_url,
    password,
    mirror_filter,
    is_search=False,
    request_from=None,
    search_string=None,
    season=None,
    episode=None,
):
    releases = []
    if not is_search:
        feed_container = soup.find(
            "table", class_="AUDIO_ITEMLIST"
        )  # it is actually called this way
        candidates = []
        if feed_container:
            for tbl in feed_container.find_all("table"):
                if tbl.find(string=re.compile(r"Erstellt am:")):
                    candidates.append(tbl)
        items = candidates
    else:
        search_table = soup.find("table", class_="SEARCH_ITEMLIST")
        items = []
        if search_table:
            items = [
                tr
                for tr in search_table.find_all("tr")
                if tr.find("p", class_="TITLE")
                and tr.find("p", class_="TITLE").find("a", href=True)
            ]

    for entry in items:
        if entry.find("table"):
            continue  # Skip header rows
        try:
            if not is_search:
                table = entry
                # title & source
                try:
                    link_tag = table.find("th").find("a")
                except AttributeError:
                    link_tag = table.find("a")
                title = link_tag.get_text(strip=True)
                if "lazylibrarian" in request_from.lower():
                    # lazylibrarian can only detect specific date formats / issue numbering for magazines
                    title = shared_state.normalize_magazine_title(title)
                else:
                    title = title.replace(" ", ".")

                source = base_url + link_tag["href"]
                # extract date and size
                date_str = size_str = None
                for row in table.find_all("tr", height=True):
                    cols = row.find_all("td")
                    if len(cols) == 2:
                        label = cols[0].get_text(strip=True)
                        val = cols[1].get_text(strip=True)
                        if label.startswith("Erstellt am"):
                            date_str = val
                        elif label.startswith("Größe"):
                            size_str = val
                published = convert_to_rss_date(date_str) if date_str else ""
                size_info = (
                    extract_size(size_str)
                    if size_str
                    else {"size": "0", "sizeunit": "MB"}
                )
                mb = float(size_info["size"])
                size_bytes = int(mb * 1024 * 1024)
                imdb_id = None
            else:
                row = entry
                title_tag = row.find("p", class_="TITLE").find("a")
                title = title_tag.get_text(strip=True)
                if "lazylibrarian" in request_from.lower():
                    # lazylibrarian can only detect specific date formats / issue numbering for magazines
                    title = shared_state.normalize_magazine_title(title)
                else:
                    title = title.replace(" ", ".")
                    if not (
                        RESOLUTION_REGEX.search(title) or CODEC_REGEX.search(title)
                    ):
                        continue

                if not shared_state.is_valid_release(
                    title, request_from, search_string, season, episode
                ):
                    continue
                if XXX_REGEX.search(title) and "xxx" not in search_string.lower():
                    continue

                source = base_url + title_tag["href"]
                date_cell = row.find_all("td")[2]
                date_str = date_cell.get_text(strip=True)
                published = convert_to_rss_date(date_str)
                size_bytes = 0
                mb = 0
                imdb_id = None

            payload = urlsafe_b64encode(
                f"{title}|{source}|{mirror_filter}|{mb}|{password}|{imdb_id}|{hostname}".encode()
            ).decode()
            link = (
                f"{shared_state.values['internal_address']}/download/?payload={payload}"
            )

            releases.append(
                {
                    "details": {
                        "title": title,
                        "hostname": hostname,
                        "imdb_id": imdb_id,
                        "link": link,
                        "mirror": mirror_filter,
                        "size": size_bytes,
                        "date": published,
                        "source": source,
                    },
                    "type": "protected",
                }
            )
        except Exception as e:
            debug(f"Error parsing {hostname.upper()}: {e}")
            continue

    return releases


def by_feed(shared_state, start_time, request_from, mirror=None):
    by = shared_state.values["config"]("Hostnames").get(hostname)
    password = by

    if "lazylibrarian" in request_from.lower():
        feed_type = "?cat=71"
    elif "radarr" in request_from.lower():
        feed_type = "?cat=1"
    else:
        feed_type = "?cat=2"

    base_url = f"https://{by}"
    url = f"{base_url}/{feed_type}"
    headers = {"User-Agent": shared_state.values["user_agent"]}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        releases = _parse_posts(
            soup,
            shared_state,
            base_url,
            password,
            request_from=request_from,
            mirror_filter=mirror,
        )
    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")
        mark_hostname_issue(
            hostname, "feed", str(e) if "e" in dir() else "Error occurred"
        )
        releases = []
    debug(f"Time taken: {time.time() - start_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases


def by_search(
    shared_state,
    start_time,
    request_from,
    search_string,
    mirror=None,
    season=None,
    episode=None,
):
    by = shared_state.values["config"]("Hostnames").get(hostname)
    password = by

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        title = get_localized_title(shared_state, imdb_id, "de")
        if not title:
            info(f"Could not extract title from IMDb-ID {imdb_id}")
            return []
        search_string = html.unescape(title)

    base_url = f"https://{by}"
    q = quote_plus(search_string)
    url = f"{base_url}/?q={q}"
    headers = {"User-Agent": shared_state.values["user_agent"]}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        releases = _parse_posts(
            soup,
            shared_state,
            base_url,
            password,
            mirror_filter=mirror,
            is_search=True,
            request_from=request_from,
            search_string=search_string,
            season=season,
            episode=episode,
        )
    except Exception as e:
        info(f"Error loading {hostname.upper()} search: {e}")
        mark_hostname_issue(
            hostname, "search", str(e) if "e" in dir() else "Error occurred"
        )
        releases = []
    debug(f"Time taken: {time.time() - start_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases
