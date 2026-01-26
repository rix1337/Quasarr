# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import html
import re
import time
from base64 import urlsafe_b64encode
from datetime import timedelta, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info

hostname = "dt"
supported_mirrors = ["rapidgator", "nitroflare", "ddownload"]


def extract_size(text):
    match = re.match(r"([\d\.]+)\s*([KMGT]B)", text, re.IGNORECASE)
    if match:
        size = match.group(1)
        unit = match.group(2).upper()
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def parse_published_datetime(article):
    date_box = article.find("div", class_="mr-2 shadow-sm1 text-center")
    mon = date_box.find("small").text.strip()
    day = date_box.find("h4").text.strip()
    year = date_box.find("h6").text.strip()
    month_num = datetime.datetime.strptime(mon, "%b").month

    time_icon = article.select_one("i.fa-clock-o")
    if time_icon:
        # its parent <span> contains e.g. "19:12"
        raw = time_icon.parent.get_text(strip=True)
        m = re.search(r"(\d{1,2}:\d{2})", raw)
        if m:
            hh, mm = map(int, m.group(1).split(":"))
        else:
            hh, mm = 0, 0
    else:
        hh, mm = 0, 0

    # this timezone is fixed to CET+1 and might be wrong
    cet = timezone(timedelta(hours=1))
    dt = datetime.datetime(int(year), month_num, int(day), hh, mm, tzinfo=cet)
    return dt.isoformat()


def dt_feed(shared_state, start_time, request_from, mirror=None):
    releases = []
    dt = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = dt

    if "lazylibrarian" in request_from.lower():
        feed_type = "learning/"
    elif "radarr" in request_from.lower():
        feed_type = "media/videos/"
    else:
        feed_type = "media/tv-show/"

    if mirror and mirror not in supported_mirrors:
        debug(
            f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported: {supported_mirrors}. Skipping!'
        )
        return releases

    url = f"https://{dt}/{feed_type}"
    headers = {"User-Agent": shared_state.values["user_agent"]}

    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        feed = BeautifulSoup(r.content, "html.parser")

        for article in feed.find_all("article"):
            try:
                link_tag = article.select_one("h4.font-weight-bold a")
                if not link_tag:
                    debug(
                        f"Link tag not found in article: {article} at {hostname.upper()}"
                    )
                    continue

                source = link_tag["href"]
                title_raw = link_tag.text.strip()
                title = (
                    title_raw.replace(" - ", "-")
                    .replace(" ", ".")
                    .replace("(", "")
                    .replace(")", "")
                )

                if "lazylibrarian" in request_from.lower():
                    # lazylibrarian can only detect specific date formats / issue numbering for magazines
                    title = shared_state.normalize_magazine_title(title)

                try:
                    imdb_id = re.search(r"tt\d+", str(article)).group()
                except:
                    imdb_id = None

                body_text = article.find("div", class_="card-body").get_text(" ")
                size_match = re.search(
                    r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB))", body_text, re.IGNORECASE
                )
                if not size_match:
                    debug(f"Size not found in article: {article} at {hostname.upper()}")
                    continue
                size_info = size_match.group(1).strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item)
                size = mb * 1024 * 1024

                published = parse_published_datetime(article)

                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}|{hostname}".encode(
                        "utf-8"
                    )
                ).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

            except Exception as e:
                info(f"Error parsing {hostname.upper()} feed: {e}")
                mark_hostname_issue(
                    hostname, "feed", str(e) if "e" in dir() else "Error occurred"
                )
                continue

            releases.append(
                {
                    "details": {
                        "title": title,
                        "hostname": hostname.lower(),
                        "imdb_id": imdb_id,
                        "link": link,
                        "mirror": mirror,
                        "size": size,
                        "date": published,
                        "source": source,
                    },
                    "type": "protected",
                }
            )

    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")
        mark_hostname_issue(
            hostname, "feed", str(e) if "e" in dir() else "Error occurred"
        )

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases


def dt_search(
    shared_state,
    start_time,
    request_from,
    search_string,
    mirror=None,
    season=None,
    episode=None,
):
    releases = []
    dt = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = dt

    if "lazylibrarian" in request_from.lower():
        cat_id = "100"
    elif "radarr" in request_from.lower():
        cat_id = "9"
    else:
        cat_id = "64"

    if mirror and mirror not in supported_mirrors:
        debug(
            f'Mirror "{mirror}" not supported by "{hostname.upper()}". Skipping search!'
        )
        return releases

    try:
        imdb_id = shared_state.is_imdb_id(search_string)
        if imdb_id:
            search_string = get_localized_title(shared_state, imdb_id, "en")
            if not search_string:
                info(f"Could not extract title from IMDb-ID {imdb_id}")
                return releases
            search_string = html.unescape(search_string)

        q = quote_plus(search_string)

        url = (
            f"https://{dt}/index.php?"
            f"do=search&"
            f"subaction=search&"
            f"search_start=0&"
            f"full_search=1&"
            f"story={q}&"
            f"catlist%5B%5D={cat_id}&"
            f"sortby=date&"
            f"resorder=desc&"
            f"titleonly=3&"
            f"searchuser=&"
            f"beforeafter=after&"
            f"searchdate=0&"
            f"replyless=0&"
            f"replylimit=0&"
            f"showposts=0"
        )
        headers = {"User-Agent": shared_state.values["user_agent"]}

        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        page = BeautifulSoup(r.content, "html.parser")

        for article in page.find_all("article"):
            try:
                link_tag = article.select_one("h4.font-weight-bold a")
                if not link_tag:
                    debug(f"No title link in search-article: {article}")
                    continue
                source = link_tag["href"]
                title_raw = link_tag.text.strip()
                title = (
                    title_raw.replace(" - ", "-")
                    .replace(" ", ".")
                    .replace("(", "")
                    .replace(")", "")
                )

                if not shared_state.is_valid_release(
                    title, request_from, search_string, season, episode
                ):
                    continue

                if "lazylibrarian" in request_from.lower():
                    # lazylibrarian can only detect specific date formats / issue numbering for magazines
                    title = shared_state.normalize_magazine_title(title)

                try:
                    imdb_id = re.search(r"tt\d+", str(article)).group()
                except:
                    imdb_id = None

                body_text = article.find("div", class_="card-body").get_text(" ")
                m = re.search(
                    r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB))", body_text, re.IGNORECASE
                )
                if not m:
                    debug(f"Size not found in search-article: {title_raw}")
                    continue
                size_item = extract_size(m.group(1).strip())
                mb = shared_state.convert_to_mb(size_item)
                size = mb * 1024 * 1024

                published = parse_published_datetime(article)

                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".encode(
                        "utf-8"
                    )
                ).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

            except Exception as e:
                info(f"Error parsing {hostname.upper()} search item: {e}")
                mark_hostname_issue(
                    hostname, "search", str(e) if "e" in dir() else "Error occurred"
                )
                continue

            releases.append(
                {
                    "details": {
                        "title": title,
                        "hostname": hostname.lower(),
                        "imdb_id": imdb_id,
                        "link": link,
                        "mirror": mirror,
                        "size": size,
                        "date": published,
                        "source": source,
                    },
                    "type": "protected",
                }
            )

    except Exception as e:
        info(f"Error loading {hostname.upper()} search page: {e}")
        mark_hostname_issue(
            hostname, "search", str(e) if "e" in dir() else "Error occurred"
        )

    elapsed = time.time() - start_time
    debug(f"Search time: {elapsed:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases
