# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import time
import traceback
import warnings
from base64 import urlsafe_b64encode
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)  # we dont want to use lxml

hostname = "wx"
supported_mirrors = []


def wx_feed(shared_state, start_time, request_from, mirror=None):
    """
    Fetch latest releases from RSS feed.
    """
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    if "lazylibrarian" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    rss_url = f'https://{host}/rss'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        response = requests.get(rss_url, headers=headers, timeout=10)

        if response.status_code != 200:
            info(f"{hostname.upper()}: RSS feed returned status {response.status_code}")
            return releases

        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('entry')

        if not items:
            items = soup.find_all('item')

        if not items:
            debug(f"{hostname.upper()}: No entries found in RSS feed")
            return releases

        max_releases = 100
        if len(items) > max_releases:
            debug(f"{hostname.upper()}: Found {len(items)} entries, limiting to {max_releases}")
            items = items[:max_releases]
        else:
            debug(f"{hostname.upper()}: Found {len(items)} entries in RSS feed")

        for item in items:
            try:
                title_tag = item.find('title')
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                if not title:
                    continue

                title = html.unescape(title)
                title = title.replace(']]>', '').replace('<![CDATA[', '')
                title = title.replace(' ', '.')

                link_tag = item.find('link', rel='alternate')
                if link_tag and link_tag.has_attr('href'):
                    source = link_tag['href']
                else:
                    link_tag = item.find('link')
                    if not link_tag:
                        continue
                    source = link_tag.get_text(strip=True)

                if not source:
                    continue

                pub_date = item.find('updated') or item.find('pubDate')
                if pub_date:
                    published = pub_date.get_text(strip=True)
                else:
                    # Fallback: use current time if no pubDate found
                    published = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

                mb = 0
                size = 0
                imdb_id = None
                password = host.upper()

                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id or ''}".encode("utf-8")
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
                        "source": source
                    },
                    "type": "protected"
                })

            except Exception as e:
                debug(f"{hostname.upper()}: error parsing RSS entry: {e}")
                continue

    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")
        return releases

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f}s ({hostname})")

    return releases


def wx_search(shared_state, start_time, request_from, search_string, mirror=None, season=None, episode=None):
    """
    Search using internal API.
    """
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    if "lazylibrarian" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        info(f"{hostname.upper()}: Received IMDb ID: {imdb_id}")
        title = get_localized_title(shared_state, imdb_id, 'de')
        if not title:
            info(f"{hostname.upper()}: no title for IMDb {imdb_id}")
            return releases
        info(f"{hostname.upper()}: Translated IMDb {imdb_id} to German title: '{title}'")
        search_string = html.unescape(title)
    else:
        info(f"{hostname.upper()}: Using search string directly: '{search_string}'")

    api_url = f'https://api.{host}/start/search'

    headers = {
        'User-Agent': shared_state.values["user_agent"],
        'Accept': 'application/json, text/plain, */*',
        'Referer': f'https://{host}/search'
    }

    params = {
        '__LOAD_P': '',
        'per_page': 50,
        'q': search_string,
        'selectedTypes': '',
        'selectedGenres': '',
        'types': 'movie,series,anime',
        'genres': '',
        'years': '',
        'ratings': '',
        'page': 1,
        'sortBy': 'latest',
        'sortOrder': 'desc'
    }

    if "sonarr" in request_from.lower():
        params['types'] = 'series,anime'
    elif "radarr" in request_from.lower():
        params['types'] = 'movie'

    info(f"{hostname.upper()}: Searching: '{search_string}'")

    try:
        response = requests.get(api_url, headers=headers, params=params, timeout=10)

        if response.status_code != 200:
            info(f"{hostname.upper()}: Search API returned status {response.status_code}")
            return releases

        data = response.json()

        if 'items' in data and 'data' in data['items']:
            items = data['items']['data']
        elif 'data' in data:
            items = data['data']
        elif 'results' in data:
            items = data['results']
        else:
            items = data if isinstance(data, list) else []

        info(f"{hostname.upper()}: Found {len(items)} items in search results")

        for item in items:
            try:
                uid = item.get('uid')
                if not uid:
                    debug(f"{hostname.upper()}: Item has no UID, skipping")
                    continue

                info(f"{hostname.upper()}: Fetching details for UID: {uid}")

                detail_url = f'https://api.{host}/start/d/{uid}'
                detail_response = requests.get(detail_url, headers=headers, timeout=10)

                if detail_response.status_code != 200:
                    debug(f"{hostname.upper()}: Detail API returned {detail_response.status_code} for {uid}")
                    continue

                detail_data = detail_response.json()

                if 'item' in detail_data:
                    detail_item = detail_data['item']
                else:
                    detail_item = detail_data

                item_imdb_id = imdb_id
                if not item_imdb_id:
                    item_imdb_id = detail_item.get('imdb_id') or detail_item.get('imdbid')
                    if not item_imdb_id and 'options' in detail_item:
                        item_imdb_id = detail_item['options'].get('imdb_id')

                source = f"https://{host}/detail/{uid}"

                main_title = detail_item.get('fulltitle') or detail_item.get('title') or detail_item.get('name')
                if main_title:
                    title = html.unescape(main_title)
                    title = title.replace(' ', '.')

                    if shared_state.is_valid_release(title, request_from, search_string, season, episode):
                        published = detail_item.get('updated_at') or detail_item.get('created_at')
                        if not published:
                            published = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
                        password = f"www.{host}"

                        payload = urlsafe_b64encode(
                            f"{title}|{source}|{mirror}|0|{password}|{item_imdb_id or ''}".encode("utf-8")
                        ).decode("utf-8")
                        link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                        releases.append({
                            "details": {
                                "title": title,
                                "hostname": hostname,
                                "imdb_id": item_imdb_id,
                                "link": link,
                                "mirror": mirror,
                                "size": 0,
                                "date": published,
                                "source": source
                            },
                            "type": "protected"
                        })

                if 'releases' in detail_item and isinstance(detail_item['releases'], list):
                    info(f"{hostname.upper()}: Found {len(detail_item['releases'])} releases for {uid}")

                    for release in detail_item['releases']:
                        try:
                            release_title = release.get('fulltitle')
                            if not release_title:
                                continue

                            release_title = html.unescape(release_title)
                            release_title = release_title.replace(' ', '.')

                            if not shared_state.is_valid_release(release_title, request_from, search_string, season,
                                                                 episode):
                                debug(f"{hostname.upper()}: ✗ Release filtered out: {release_title}")
                                continue

                            release_uid = release.get('uid')
                            if release_uid:
                                release_source = f"https://{host}/detail/{uid}?release={release_uid}"
                            else:
                                release_source = source

                            release_published = release.get('updated_at') or release.get(
                                'created_at') or detail_item.get('updated_at')
                            if not release_published:
                                release_published = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
                            release_size = release.get('size', 0)
                            password = f"www.{host}"

                            payload = urlsafe_b64encode(
                                f"{release_title}|{release_source}|{mirror}|{release_size}|{password}|{item_imdb_id or ''}".encode(
                                    "utf-8")
                            ).decode("utf-8")
                            link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                            releases.append({
                                "details": {
                                    "title": release_title,
                                    "hostname": hostname,
                                    "imdb_id": item_imdb_id,
                                    "link": link,
                                    "mirror": mirror,
                                    "size": release_size,
                                    "date": release_published,
                                    "source": release_source
                                },
                                "type": "protected"
                            })

                        except Exception as e:
                            debug(f"{hostname.upper()}: Error parsing release: {e}")
                            continue
                else:
                    debug(f"{hostname.upper()}: No releases array found for {uid}")

            except Exception as e:
                debug(f"{hostname.upper()}: Error processing item: {e}")
                debug(f"{hostname.upper()}: {traceback.format_exc()}")
                continue

        info(f"{hostname.upper()}: Returning {len(releases)} total releases")

    except Exception as e:
        info(f"Error in {hostname.upper()} search: {e}")

        debug(f"{hostname.upper()}: {traceback.format_exc()}")
        return releases

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f}s ({hostname})")

    return releases
