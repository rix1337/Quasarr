# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta

import requests

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

hostname = "sf"
supported_mirrors = ["1fichier", "ddownload", "katfile", "rapidgator", "turbobit"]

from bs4 import BeautifulSoup


def parse_mirrors(base_url, entry):
    """
    entry: a BeautifulSoup Tag for <div class="entry">
    returns a dict with:
      - name:        header text
      - season:      list of {host: link}
      - episodes:    list of {number, title, links}
    """

    mirrors = {}

    try:
        host_map = {
            '1F': '1fichier',
            'DD': 'ddownload',
            'KA': 'katfile',
            'RG': 'rapidgator',
            'TB': 'turbobit'
        }

        h3 = entry.select_one('h3')
        name = h3.get_text(separator=' ', strip=True) if h3 else ''

        season = {}
        for a in entry.select('a.dlb.row'):
            if a.find_parent('div.list.simple'):
                continue
            host = a.get_text(strip=True)
            if len(host) > 2:  # episode hosts are 2 chars
                season[host] = f"{base_url}{a['href']}"

        episodes = []
        for ep_row in entry.select('div.list.simple > div.row'):
            if 'head' in ep_row.get('class', []):
                continue

            divs = ep_row.find_all('div', recursive=False)
            number = int(divs[0].get_text(strip=True).rstrip('.'))
            title = divs[1].get_text(strip=True)

            ep_links = {}
            for a in ep_row.select('div.row > a.dlb.row'):
                host = a.get_text(strip=True)
                full_host = host_map.get(host, host)
                ep_links[full_host] = f"{base_url}{a['href']}"

            episodes.append({
                'number': number,
                'title': title,
                'links': ep_links
            })

        mirrors = {
            'name': name,
            'season': season,
            'episodes': episodes
        }
    except Exception as e:
        info(f"Error parsing mirrors: {e}")

    return mirrors


def sf_feed(shared_state, start_time, request_from, mirror=None):
    releases = []
    sf = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = sf

    if "Radarr" in request_from:
        debug(f'Skipping Radarr search on "{hostname.upper()}" (unsupported media type at hostname)!')
        return releases

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
              ' Skipping search!')
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
            response = requests.get(f"https://{sf}/updates/{formatted_date}#list", headers, timeout=10)
        except Exception as e:
            info(f"Error loading {hostname.upper()} feed: {e} for {formatted_date}")
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
                            f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode("utf-8")
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
                            "title": title,
                            "hostname": hostname.lower(),
                            "imdb_id": imdb_id,
                            "link": link,
                            "mirror": mirror,
                            "size": size,
                            "date": published,
                            "source": source,
                        },
                        "type": "protected"
                    })

            except Exception as e:
                info(f"Error parsing {hostname.upper()} feed: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds ({hostname.lower()})")

    return releases


def extract_season_episode(search_string):
    try:
        match = re.search(r'(.*?)(S\d{1,3})(?:E(\d{1,3}))?', search_string, re.IGNORECASE)
        if match:
            season = int(match.group(2)[1:])
            episode = int(match.group(3)) if match.group(3) else None
            return season, episode
    except Exception as e:
        debug(f"Error extracting season / episode from {search_string}: {e}")
    return None, None


def extract_size(text):
    match = re.match(r"(\d+(\.\d+)?) ([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(3)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def sf_search(shared_state, start_time, request_from, search_string, mirror=None):
    releases = []
    sf = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = sf

    season, episode = extract_season_episode(search_string)

    if "Radarr" in request_from:
        debug(f'Skipping Radarr search on "{hostname.upper()}" (unsupported media type at hostname)!')
        return releases

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
              ' Skipping search!')
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
        info(f"Error loading {hostname.upper()} search: {e}")
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
                    threshold = 15  # this should cut down duplicates in case Sonarr is searching variants of a title
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
                        title = details.find("small").text.strip()

                        if not shared_state.search_string_in_sanitized_title(search_string, title):
                            continue

                        size_string = item.find("span", {"class": "morespec"}).text.split("|")[1].strip()
                        size_item = extract_size(size_string)
                        mirrors = parse_mirrors(f"https://{sf}", details)

                        if mirror:
                            if mirror not in mirrors["season"]:
                                continue
                            source = mirrors["season"][mirror]
                            if not source:
                                info(f"Could not find mirror '{mirror}' for '{title}'")
                        else:
                            source = next(iter(mirrors["season"]))
                    except:
                        debug(f"Could not find link for '{search_string}'")
                        continue

                    mb = shared_state.convert_to_mb(size_item)

                    if episode:
                        mb = 0
                        try:
                            if not re.search(r'S\d{1,3}E\d{1,3}', title):
                                title = re.sub(r'(S\d{1,3})', rf'\1E{episode:02d}', title)

                                # Count episodes
                                episodes_in_release = len(mirrors["episodes"])

                                # Get the correct episode entry (episode numbers are 1-based, list index is 0-based)
                                episode_data = next((e for e in mirrors["episodes"] if e["number"] == int(episode)),
                                                    None)

                                if episode_data:
                                    if mirror:
                                        if mirror not in episode_data["links"]:
                                            debug(
                                                f"Mirror '{mirror}' does not exist for '{title}' episode {episode}'")
                                        else:
                                            source = episode_data["links"][mirror]

                                    else:
                                        source = next(iter(episode_data["links"].values()))
                                else:
                                    debug(f"Episode '{episode}' data not found in mirrors for '{title}'")

                                if episodes_in_release:
                                    mb = shared_state.convert_to_mb({
                                        "size": float(size_item["size"]) // episodes_in_release,
                                        "sizeunit": size_item["sizeunit"]
                                    })
                        except:
                            continue

                    payload = urlsafe_b64encode(f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".
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
                            "title": title,
                            "hostname": hostname.lower(),
                            "imdb_id": imdb_id,
                            "link": link,
                            "mirror": mirror,
                            "size": size,
                            "date": published,
                            "source": f"{series_url}/{season}" if season else series_url
                        },
                        "type": "protected"
                    })

            except Exception as e:
                info(f"Error parsing {hostname.upper()} search: {e}")
        else:
            debug(f"Search string '{search_string}' does not match result '{result['title']}'")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds ({hostname.lower()})")

    return releases
