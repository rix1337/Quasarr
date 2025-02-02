# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug


def sf_feed(shared_state, start_time, request_from):
    releases = []
    sf = shared_state.values["config"]("Hostnames").get("sf")
    password = sf

    if "Radarr" in request_from:
        debug(f"Skipped Radarr search (sf)")
        return releases

    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    date = datetime.now()
    days_to_cover = 2

    while days_to_cover > 0:
        days_to_cover -= 1
        formatted_date = date.strftime('%Y-%m-%d')
        date -= timedelta(days=1)

        try:
            response = requests.get(f"https://serienfans.org/updates/{formatted_date}#list", headers, timeout=10)
        except Exception as e:
            info(f"Error loading SF feed: {e} for {formatted_date}")
            return releases

        content = BeautifulSoup(response.text, "html.parser")
        items = content.find_all("div", {"class": "row"}, style=re.compile("order"))

        for item in items:
            try:
                a = item.find("a", href=re.compile("/"))
                title = a.text

                if title:
                    try:
                        source = f"https://{sf}{a['href']}"
                        mb = 0  # size info is missing here
                        imdb_id = None  # imdb info is missing here

                        payload = urlsafe_b64encode(
                            f"{title}|{source}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode("utf-8")
                        link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                    except:
                        continue

                    try:
                        size = mb * 1024 * 1024
                    except:
                        continue

                    try:
                        published_time = item.find("div", {"class": "datime"}).text
                        published = f"{formatted_date}T{published_time}:00"
                    except:
                        continue

                    releases.append({
                        "details": {
                            "title": f"[SF] {title}",
                            "imdb_id": imdb_id,
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": source,
                        },
                        "type": "protected"
                    })

            except Exception as e:
                info(f"Error parsing SF feed: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds (sf)")

    return releases


def extract_season_episode(search_string):
    match = re.search(r'(.*?)(S\d{1,3})(?:E(\d{1,3}))?', search_string, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        season = int(match.group(2)[1:])
        episode = int(match.group(3)) if match.group(3) else None
        return title, season, episode
    return search_string, None, None


def extract_size(text):
    match = re.match(r"(\d+(\.\d+)?) ([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(3)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def sf_search(shared_state, start_time, request_from, search_string):
    releases = []
    sf = shared_state.values["config"]("Hostnames").get("sf")
    password = sf

    title, season, episode = extract_season_episode(search_string)

    if "Radarr" in request_from:
        debug(f"Skipped Radarr search (sf)")
        return releases

    if re.match(r'^tt\d{7,8}$', search_string):
        imdb_id = search_string
        search_string = get_localized_title(shared_state, imdb_id, 'de')
        if not search_string:
            info(f"Could not extract title from IMDb-ID {imdb_id}")
            return releases
        search_string = html.unescape(search_string)

    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

    url = f'https://{sf}/api/v2/search?q={search_string}&ql=DE'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(url, headers, timeout=10)
        feed = response.json()
    except Exception as e:
        info(f"Error loading SF search: {e}")
        return releases

    results = feed['result']
    for result in results:
        sanitized_search_string = shared_state.sanitize_string(search_string)
        sanitized_title = shared_state.sanitize_string(result["title"])

        # Use word boundaries to ensure full word/phrase match
        if re.search(rf'\b{re.escape(sanitized_search_string)}\b', sanitized_title):
            debug(f"Matched search string '{search_string}' with result '{result['title']}'")
            try:
                try:
                    if not season:
                        season = "ALL"

                    series_id = result["url_id"]
                    threshold = 30
                    context = "recents_sf"
                    recently_searched = shared_state.get_recently_searched(shared_state, context, threshold)
                    if series_id in recently_searched:
                        if recently_searched[series_id]["timestamp"] > datetime.now() - timedelta(seconds=threshold):
                            debug(f"'/{series_id}' - requested within the last {threshold} seconds! Skipping...")
                            continue

                    recently_searched[series_id] = {"timestamp": datetime.now()}
                    shared_state.update(context, recently_searched)

                    series_url = f"https://{sf}/{series_id}"
                    series_page = requests.get(series_url, headers, timeout=10).text
                    try:
                        imdb_link = (BeautifulSoup(series_page, "html.parser").
                                     find("a", href=re.compile(r"imdb\.com")))
                        imdb_id = re.search(r'tt\d+', str(imdb_link)).group()
                    except:
                        imdb_id = None

                    season_id = re.findall(r"initSeason\('(.+?)\',", series_page)[0]
                    epoch = str(datetime.now().timestamp()).replace('.', '')[:-3]
                    api_url = 'https://' + sf + '/api/v1/' + season_id + f'/season/{season}?lang=ALL&_=' + epoch

                    response = requests.get(api_url, headers=headers, timeout=10)
                    data = response.json()["html"]
                    content = BeautifulSoup(data, "html.parser")

                    items = content.find_all("h3")
                except:
                    continue

                for item in items:
                    try:
                        details = item.parent.parent.parent
                        name = details.find("small").text.strip()

                        if not shared_state.search_string_in_sanitized_title(search_string, name):
                            continue

                        size_string = item.find("span", {"class": "morespec"}).text.split("|")[1].strip()
                        size_item = extract_size(size_string)
                        source = f'https://{sf}{details.find("a")["href"]}'
                    except:
                        continue

                    mb = shared_state.convert_to_mb(size_item)

                    if episode:
                        mb = 0
                        try:
                            if not re.search(r'S\d{1,3}E\d{1,3}', name):
                                name = re.sub(r'(S\d{1,3})', rf'\1E{episode:02d}', name)

                                item_details = details.find("div", {"class": "list simple"})
                                details_episodes = item_details.find_all("div", {"class": "row"})
                                episodes_in_release = 0

                                for row in details_episodes:
                                    main_row = row.find_all("div", {"class": "row"})
                                    links_in_row = row.find_all("a", {"class": "dlb row"})
                                    if main_row and links_in_row:
                                        episodes_in_release += 1
                                        if episodes_in_release == episode:
                                            source = f'https://{sf}{links_in_row[0]["href"]}'

                                if episodes_in_release:
                                    mb = shared_state.convert_to_mb({
                                        "size": float(size_item["size"]) // episodes_in_release,
                                        "sizeunit": size_item["sizeunit"]
                                    })
                        except:
                            continue

                    payload = urlsafe_b64encode(f"{name}|{source}|{mb}|{password}|{imdb_id}".
                                                encode("utf-8")).decode("utf-8")
                    link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                    try:
                        size = mb * 1024 * 1024
                    except:
                        continue

                    try:
                        published = one_hour_ago  # release date is missing here
                    except:
                        continue

                    releases.append({
                        "details": {
                            "title": f"[SF] {name}",
                            "imdb_id": imdb_id,
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": f"{series_url}/{season}" if season else series_url
                        },
                        "type": "protected"
                    })

            except Exception as e:
                info(f"Error parsing SF search: {e}")
        else:
            debug(f"Search string '{search_string}' does not match result '{result['title']}'")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds (sf)")

    return releases
