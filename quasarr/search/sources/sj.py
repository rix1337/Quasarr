# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "sj"


def convert_to_rss_date(date_str):
    try:
        return datetime.fromisoformat(
            date_str.replace("Z", "+00:00")
        ).strftime("%a, %d %b %Y %H:%M:%S +0000")
    except Exception:
        return ""


def sj_feed(shared_state, start_time, request_from, mirror=None):
    releases = []

    if "sonarr" not in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    sj_host = shared_state.values["config"]("Hostnames").get(hostname)
    password = sj_host

    url = f"https://{sj_host}/api/releases/latest/0"
    headers = {"User-Agent": shared_state.values["user_agent"]}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = json.loads(r.content)
    except Exception as e:
        info(f"{hostname.upper()}: feed load error: {e}")
        return releases

    for release in data:
        try:
            title = release.get("name").rstrip(".")
            if not title:
                continue

            published = convert_to_rss_date(release.get("createdAt"))
            if not published:
                continue

            media = release.get("_media", {})
            slug = media.get("slug")
            if not slug:
                continue

            series_url = f"https://{sj_host}/serie/{slug}"

            mb = 0
            size = 0
            imdb_id = None

            payload = urlsafe_b64encode(
                f"{title}|{series_url}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")
            ).decode("utf-8")

            link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

            releases.append({
                "details": {
                    "title": title,
                    "hostname": hostname,
                    "imdb_id": imdb_id,
                    "link": link,
                    "mirror": mirror,
                    "size": size,
                    "date": published,
                    "source": series_url
                },
                "type": "protected"
            })

        except Exception as e:
            debug(f"{hostname.upper()}: feed parse error: {e}")
            continue

    debug(f"Time taken: {time.time() - start_time:.2f}s ({hostname})")
    return releases


def sj_search(shared_state, start_time, request_from, search_string, mirror=None, season=None, episode=None):
    releases = []

    if "sonarr" not in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    sj_host = shared_state.values["config"]("Hostnames").get(hostname)
    password = sj_host

    imdb_id = shared_state.is_imdb_id(search_string)
    if not imdb_id:
        return releases

    localized_title = get_localized_title(shared_state, imdb_id, "de")
    if not localized_title:
        info(f"{hostname.upper()}: no localized title for IMDb {imdb_id}")
        return releases

    headers = {"User-Agent": shared_state.values["user_agent"]}
    search_url = f"https://{sj_host}/serie/search"
    params = {"q": localized_title}

    try:
        r = requests.get(search_url, headers=headers, params=params, timeout=10)
        soup = BeautifulSoup(r.content, "html.parser")
        results = soup.find_all("a", href=re.compile(r"^/serie/"))
    except Exception as e:
        info(f"{hostname.upper()}: search load error: {e}")
        return releases

    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    sanitized_search_string = shared_state.sanitize_string(localized_title)

    for result in results:
        try:
            result_title = result.get_text(strip=True)

            sanitized_title = shared_state.sanitize_string(result_title)

            if not re.search(
                    rf"\b{re.escape(sanitized_search_string)}\b",
                    sanitized_title
            ):
                debug(
                    f"Search string '{localized_title}' doesn't match '{result_title}'"
                )
                continue

            debug(
                f"Matched search string '{localized_title}' with result '{result_title}'"
            )

            series_url = f"https://{sj_host}{result['href']}"

            r = requests.get(series_url, headers=headers, timeout=10)
            media_id_match = re.search(r'data-mediaid="([^"]+)"', r.text)
            if not media_id_match:
                debug(f"{hostname.upper()}: no media id for {result_title}")
                continue

            media_id = media_id_match.group(1)
            api_url = f"https://{sj_host}/api/media/{media_id}/releases"

            r = requests.get(api_url, headers=headers, timeout=10)
            data = json.loads(r.content)

            for season_block in data.values():
                for item in season_block.get("items", []):
                    title = item.get("name").rstrip(".")
                    if not title:
                        continue

                    if not shared_state.is_valid_release(
                            title,
                            request_from,
                            search_string,
                            season,
                            episode
                    ):
                        continue

                    published = convert_to_rss_date(item.get("createdAt"))
                    if not published:
                        debug(f"{hostname.upper()}: no published date for {title}")
                        published = one_hour_ago

                    mb = 0
                    size = 0

                    payload = urlsafe_b64encode(
                        f"{title}|{series_url}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")
                    ).decode("utf-8")

                    link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                    releases.append({
                        "details": {
                            "title": title,
                            "hostname": hostname,
                            "imdb_id": imdb_id,
                            "link": link,
                            "mirror": mirror,
                            "size": size,
                            "date": published,
                            "source": series_url
                        },
                        "type": "protected"
                    })

        except Exception as e:
            debug(f"{hostname.upper()}: search parse error: {e}")
            continue

    debug(f"Time taken: {time.time() - start_time:.2f}s ({hostname})")
    return releases
