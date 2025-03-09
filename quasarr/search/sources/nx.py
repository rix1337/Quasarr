# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import time
from base64 import urlsafe_b64encode

import requests

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "nx"
supported_mirrors = ["filer"]


def nx_feed(shared_state, start_time, request_from, mirror=None):
    releases = []
    nx = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = nx

    if "Radarr" in request_from:
        category = "movie"
    else:
        category = "episode"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
              ' Skipping search!')
        return releases

    url = f'https://{nx}/api/frontend/releases/category/{category}/tag/all/1/51?sort=date'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(url, headers, timeout=10)
        feed = response.json()
    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")
        return releases

    items = feed['result']['list']
    for item in items:
        try:
            title = item['name']

            if title:
                try:
                    source = f"https://{nx}/release/{item['slug']}"
                    imdb_id = item.get('_media', {}).get('imdbid', None)
                    mb = shared_state.convert_to_mb(item)
                    payload = urlsafe_b64encode(
                        f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode(
                        "utf-8")
                    link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                except:
                    continue

                try:
                    size = mb * 1024 * 1024
                except:
                    continue

                try:
                    published = item['publishat']
                except:
                    continue

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
            info(f"Error parsing {hostname.upper()} feed: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds ({hostname.lower()})")

    return releases


def nx_search(shared_state, start_time, request_from, search_string, mirror=None):
    releases = []
    nx = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = nx

    if "Radarr" in request_from:
        valid_type = "movie"
    else:
        valid_type = "episode"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
              ' Skipping search!')
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        search_string = get_localized_title(shared_state, imdb_id, 'de')
        if not search_string:
            info(f"Could not extract title from IMDb-ID {imdb_id}")
            return releases
        search_string = html.unescape(search_string)

    url = f'https://{nx}/api/frontend/search/{search_string}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(url, headers, timeout=10)
        feed = response.json()
    except Exception as e:
        info(f"Error loading {hostname.upper()} search: {e}")
        return releases

    items = feed['result']['releases']
    for item in items:
        try:
            if item['type'] == valid_type:
                title = item['name']
                if title:
                    if not shared_state.search_string_in_sanitized_title(search_string, title):
                        continue

                    try:
                        source = f"https://{nx}/release/{item['slug']}"
                        if not imdb_id:
                            imdb_id = item.get('_media', {}).get('imdbid', None)

                        mb = shared_state.convert_to_mb(item)
                        payload = urlsafe_b64encode(f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".
                                                    encode("utf-8")).decode("utf-8")
                        link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                    except:
                        continue

                    try:
                        size = mb * 1024 * 1024
                    except:
                        continue

                    try:
                        published = item['publishat']
                    except:
                        published = ""

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
            info(f"Error parsing {hostname.upper()} search: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds ({hostname.lower()})")

    return releases
