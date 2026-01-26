# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta
from urllib.parse import quote, quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info

hostname = "wd"
supported_mirrors = ["rapidgator", "ddownload", "katfile", "fikper", "turbobit"]

# regex to detect porn-tag .XXX. (case-insensitive, dots included)
XXX_REGEX = re.compile(r"\.xxx\.", re.I)
# regex to detect video resolution
RESOLUTION_REGEX = re.compile(r"\d{3,4}p", re.I)
# regex to detect video codec tags
CODEC_REGEX = re.compile(r"x264|x265|h264|h265|hevc|avc", re.I)


def convert_to_rss_date(date_str):
    """
    date_str comes in as "02.05.2025 - 09:04"
    Return RFC‑822 style date with +0000 timezone.
    """
    parsed = datetime.strptime(date_str, "%d.%m.%Y - %H:%M")
    return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")


def extract_size(text):
    """
    e.g. "8 GB" → {"size": "8", "sizeunit": "GB"}
    """
    match = re.match(r"(\d+(?:\.\d+)?)\s*([A-Za-z]+)", text)
    if not match:
        raise ValueError(f"Invalid size format: {text!r}")
    return {"size": match.group(1), "sizeunit": match.group(2)}


def _parse_rows(
    soup,
    shared_state,
    url_base,
    password,
    mirror_filter,
    request_from=None,
    search_string=None,
    season=None,
    episode=None,
):
    """
    Walk the <table> rows, extract one release per row.
    Only include rows with at least one supported mirror.
    If mirror_filter provided, only include rows where mirror_filter is present.

    Context detection:
      - feed when search_string is None
      - search when search_string is a str

    Porn-filtering:
      - feed: always drop .XXX.
      - search: drop .XXX. unless 'xxx' in search_string (case-insensitive)

    If in search context, also filter out non-video releases (ebooks, games).
    """
    releases = []
    is_search = search_string is not None

    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    for tr in soup.select("table.table tbody tr.lh-sm"):
        try:
            a = tr.find("a", class_="upload-link")
            raw_href = a["href"]
            href = quote(raw_href, safe="/?:=&")
            source = f"https://{url_base}{href}"

            preview_div = a.find("div", class_="preview-text")
            date_txt = preview_div.get_text(strip=True) if preview_div else None
            if preview_div:
                preview_div.extract()

            title = a.get_text(strip=True)

            # search context contains non-video releases (ebooks, games, etc.)
            if is_search:
                if not shared_state.is_valid_release(
                    title, request_from, search_string, season, episode
                ):
                    continue

                if "lazylibrarian" in request_from.lower():
                    # lazylibrarian can only detect specific date formats / issue numbering for magazines
                    title = shared_state.normalize_magazine_title(title)
                else:
                    # drop .XXX. unless user explicitly searched xxx
                    if XXX_REGEX.search(title) and "xxx" not in search_string.lower():
                        continue
                    # require resolution/codec
                    if not (
                        RESOLUTION_REGEX.search(title) or CODEC_REGEX.search(title)
                    ):
                        continue
                    # require no spaces in title
                    if " " in title:
                        continue

            hoster_names = tr.find("span", class_="button-warezkorb")[
                "data-hoster-names"
            ]
            mirrors = [m.strip().lower() for m in hoster_names.split(",")]
            valid = [m for m in mirrors if m in supported_mirrors]
            if not valid or (mirror_filter and mirror_filter not in valid):
                continue

            size_txt = tr.find("span", class_="element-size").get_text(strip=True)
            sz = extract_size(size_txt)
            mb = shared_state.convert_to_mb(sz)
            size_bytes = mb * 1024 * 1024

            imdb_id = None
            published = convert_to_rss_date(date_txt) if date_txt else one_hour_ago

            payload = urlsafe_b64encode(
                f"{title}|{source}|{mirror_filter}|{mb}|{password}|{imdb_id}|{hostname}".encode()
            ).decode()
            download_link = (
                f"{shared_state.values['internal_address']}/download/?payload={payload}"
            )

            releases.append(
                {
                    "details": {
                        "title": title,
                        "hostname": hostname,
                        "imdb_id": imdb_id,
                        "link": download_link,
                        "mirror": mirror_filter,
                        "size": size_bytes,
                        "date": published,
                        "source": source,
                    },
                    "type": "protected",
                }
            )
        except Exception as e:
            debug(f"Error parsing {hostname.upper()} row: {e}")
            continue
    return releases


def wd_feed(shared_state, start_time, request_from, mirror=None):
    wd = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = wd

    if "lazylibrarian" in request_from.lower():
        feed_type = "Ebooks"
    elif "radarr" in request_from.lower():
        feed_type = "Movies"
    else:
        feed_type = "Serien"

    url = f"https://{wd}/{feed_type}"
    headers = {"User-Agent": shared_state.values["user_agent"]}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        releases = _parse_rows(soup, shared_state, wd, password, mirror)
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


def wd_search(
    shared_state,
    start_time,
    request_from,
    search_string,
    mirror=None,
    season=None,
    episode=None,
):
    releases = []
    wd = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = wd

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        search_string = get_localized_title(shared_state, imdb_id, "de")
        if not search_string:
            info(f"Could not extract title from IMDb-ID {imdb_id}")
            return releases
        search_string = html.unescape(search_string)

    q = quote_plus(search_string)
    url = f"https://{wd}/search?q={q}"
    headers = {"User-Agent": shared_state.values["user_agent"]}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        releases = _parse_rows(
            soup,
            shared_state,
            wd,
            password,
            mirror,
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
