# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
from base64 import urlsafe_b64encode

import requests

from quasarr.providers.imdb_metadata import get_localized_title


def convert_to_bytes(item):
    size = float(item['size'])
    unit = item['sizeunit'].upper()

    if unit == 'B':
        size_b = size
    elif unit == 'KB':
        size_b = size * 1024
    elif unit == 'MB':
        size_b = size * 1024 * 1024
    elif unit == 'GB':
        size_b = size * 1024 * 1024 * 1024
    elif unit == 'TB':
        size_b = size * 1024 * 1024 * 1024 * 1024
    else:
        raise ValueError(f"Unsupported size unit {item['name']} {item['size']} {item['sizeunit']}")

    return int(size_b)


def nx_feed(shared_state, request_from):
    releases = []

    if "Radarr" in request_from:
        category = "movie"
    else:
        category = "episode"

    nx = shared_state.values["config"]("Hostnames").get("nx")

    feed = f'https://{nx}/api/frontend/releases/category/{category}/tag/all/1/51?sort=date'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(feed, headers)
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
                    source = "https://" + nx + "/release/" + item['slug']
                    payload = urlsafe_b64encode(f"{title}|{source}".encode("utf-8")).decode("utf-8")
                    link = f"{shared_state.values['external_address']}/download/?payload={payload}"  # ToDo will not work with auth
                except:
                    continue

                try:
                    size = convert_to_bytes(item)
                except:
                    continue

                try:
                    published = item['publishat']
                except:
                    continue

                releases.append({
                    "details": {
                        "title": title,
                        "link": link,
                        "size": size,
                        "date": published
                    },
                    "type": "protected"
                })

        except Exception as e:
            print(f"Error parsing NX feed: {e}")

    return releases


def nx_search(shared_state, request_from, imdb_id):
    releases = []

    if "Radarr" in request_from:
        valid_type = "movie"
    else:
        valid_type = "episode"

    nx = shared_state.values["config"]("Hostnames").get("nx")

    german_title = get_localized_title(shared_state, imdb_id, 'de')
    if not german_title:
        print(f"German title from IMDb required for NX search")
        return releases

    german_title = html.unescape(german_title)

    feed = f'https://{nx}/api/frontend/search/{german_title}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(feed, headers)
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
                        source = "https://" + nx + "/release/" + item['slug']
                        payload = urlsafe_b64encode(f"{title}|{source}".encode("utf-8")).decode("utf-8")
                        link = f"{shared_state.values['external_address']}/download/?payload={payload}"  # ToDo will not work with auth
                    except:
                        continue

                    try:
                        size = convert_to_bytes(item)
                    except:
                        continue

                    try:
                        published = item['publishat']
                    except:
                        published = ""

                    releases.append({
                        "details": {
                            "title": title,
                            "link": link,
                            "size": size,
                            "date": published
                        },
                        "type": "protected"
                    })

        except Exception as e:
            print(f"Error parsing NX search: {e}")

    return releases
