# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
from base64 import urlsafe_b64encode

import requests

from quasarr.providers.imdb_metadata import get_localized_title


def nx_feed(shared_state, request_from):
    releases = []
    nx = shared_state.values["config"]("Hostnames").get("nx")
    password = nx

    if "Radarr" in request_from:
        category = "movie"
    else:
        category = "episode"

    url = f'https://{nx}/api/frontend/releases/category/{category}/tag/all/1/51?sort=date'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(url, headers)
        feed = response.json()
    except Exception as e:
        print(f"Error loading NX feed: {e}")
        return releases

    items = feed['result']['list']
    for item in items:
        try:
            title = item['name']
            if title:
                try:
                    source = f"https://{nx}/release/{item['slug']}"
                    mb = shared_state.convert_to_mb(item)
                    payload = urlsafe_b64encode(f"{title}|{source}|{mb}|{password}".encode("utf-8")).decode("utf-8")
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
                        "title": f"[NX] {title}",
                        "link": link,
                        "size": size,
                        "date": published,
                        "source": source
                    },
                    "type": "protected"
                })

        except Exception as e:
            print(f"Error parsing NX feed: {e}")

    return releases


def nx_search(shared_state, request_from, search_string):
    releases = []
    nx = shared_state.values["config"]("Hostnames").get("nx")
    password = nx

    if "Radarr" in request_from:
        valid_type = "movie"
    else:
        valid_type = "episode"

    if re.match(r'^tt\d{7,8}$', search_string):
        imdb_id = search_string
        search_string = get_localized_title(shared_state, imdb_id, 'de')
        if not search_string:
            print(f"Could not extract title from IMDb-ID {imdb_id}")
            return releases
        search_string = html.unescape(search_string)

    url = f'https://{nx}/api/frontend/search/{search_string}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(url, headers)
        feed = response.json()
    except Exception as e:
        print(f"Error loading NX search: {e}")
        return releases

    items = feed['result']['releases']
    for item in items:
        try:
            if item['type'] == valid_type:
                title = item['name']
                if title:
                    try:
                        source = f"https://{nx}/release/{item['slug']}"
                        mb = shared_state.convert_to_mb(item)
                        payload = urlsafe_b64encode(f"{title}|{source}|{mb}|{password}".
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
                            "title": f"[NX] {title}",
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": source
                        },
                        "type": "protected"
                    })

        except Exception as e:
            print(f"Error parsing NX search: {e}")

    return releases
