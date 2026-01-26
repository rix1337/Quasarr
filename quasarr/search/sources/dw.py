# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import re
import time
from base64 import urlsafe_b64encode

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info

hostname = "dw"
supported_mirrors = ["1fichier", "rapidgator", "ddownload", "katfile"]


def convert_to_rss_date(date_str):
    german_months = [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    english_months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]

    for german, english in zip(german_months, english_months):
        if german in date_str:
            date_str = date_str.replace(german, english)
            break

    parsed_date = datetime.datetime.strptime(date_str, "%d. %B %Y / %H:%M")
    rss_date = parsed_date.strftime("%a, %d %b %Y %H:%M:%S %z")

    return rss_date


def extract_size(text):
    # First try the normal pattern: number + space + unit (e.g., "1024 MB")
    match = re.match(r"(\d+)\s+([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}

    # If that fails, try pattern with just unit (e.g., "MB")
    unit_match = re.match(r"([A-Za-z]+)", text.strip())
    if unit_match:
        unit = unit_match.group(1)
        # Fall back to 0 when size is missing
        return {"size": "0", "sizeunit": unit}

    # If neither pattern matches, raise the original error
    raise ValueError(f"Invalid size format: {text}")


def dw_feed(shared_state, start_time, request_from, mirror=None):
    releases = []
    dw = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = dw

    if not "arr" in request_from.lower():
        debug(
            f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!'
        )
        return releases

    if "Radarr" in request_from:
        feed_type = "videos/filme/"
    else:
        feed_type = "videos/serien/"

    if mirror and mirror not in supported_mirrors:
        debug(
            f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
            " Skipping search!"
        )
        return releases

    url = f"https://{dw}/{feed_type}"
    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        feed = BeautifulSoup(r.content, "html.parser")
        articles = feed.find_all("h4")

        for article in articles:
            try:
                source = article.a["href"]
                title = article.a.text.strip()

                try:
                    imdb_id = re.search(r"tt\d+", str(article)).group()
                except:
                    imdb_id = None

                size_info = article.find("span").text.strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item)
                size = mb * 1024 * 1024
                date = article.parent.parent.find(
                    "span", {"class": "date updated"}
                ).text.strip()
                published = convert_to_rss_date(date)
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

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases


def dw_search(
    shared_state,
    start_time,
    request_from,
    search_string,
    mirror=None,
    season=None,
    episode=None,
):
    releases = []
    dw = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = dw

    if not "arr" in request_from.lower():
        debug(
            f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!'
        )
        return releases

    if "Radarr" in request_from:
        search_type = "videocategory=filme"
    else:
        search_type = "videocategory=serien"

    if mirror and mirror not in ["1fichier", "rapidgator", "ddownload", "katfile"]:
        debug(
            f'Mirror "{mirror}" not not supported by {hostname.upper()}. Skipping search!'
        )
        return releases

    url = f"https://{dw}/?s={search_string}&{search_type}"
    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        search = BeautifulSoup(r.content, "html.parser")
        results = search.find_all("h4")

    except Exception as e:
        info(f"Error loading {hostname.upper()} search feed: {e}")
        mark_hostname_issue(
            hostname, "search", str(e) if "e" in dir() else "Error occurred"
        )
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)

    if results:
        for result in results:
            try:
                title = result.a.text.strip()

                if not shared_state.is_valid_release(
                    title, request_from, search_string, season, episode
                ):
                    continue

                if not imdb_id:
                    try:
                        imdb_id = re.search(r"tt\d+", str(result)).group()
                    except:
                        imdb_id = None

                source = result.a["href"]
                size_info = result.find("span").text.strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item)
                size = mb * 1024 * 1024
                date = result.parent.parent.find(
                    "span", {"class": "date updated"}
                ).text.strip()
                published = convert_to_rss_date(date)
                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}|{hostname}".encode(
                        "utf-8"
                    )
                ).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
            except Exception as e:
                info(f"Error parsing {hostname.upper()} search: {e}")
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

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases
