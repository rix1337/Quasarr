# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
import warnings
from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import unescape

from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning

from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug
from quasarr.providers.sessions.dl import retrieve_and_validate_session, invalidate_session, fetch_via_requests_session

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)  # we dont want to use lxml

hostname = "dl"
supported_mirrors = []


def normalize_title_for_sonarr(title):
    """
    Normalize title for Sonarr by replacing spaces with dots.
    """
    title = title.replace(' ', '.')
    title = re.sub(r'\s*-\s*', '-', title)
    title = re.sub(r'\.\-\.', '-', title)
    title = re.sub(r'\.{2,}', '.', title)
    title = title.strip('.')
    return title


def dl_feed(shared_state, start_time, request_from, mirror=None):
    """
    Parse the RSS feed and return releases.
    """
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    if not host:
        debug(f"{hostname}: hostname not configured")
        return releases

    try:
        sess = retrieve_and_validate_session(shared_state)
        if not sess:
            info(f"Could not retrieve valid session for {host}")
            return releases

        # Instead we should parse the HTML for the correct *arr client
        rss_url = f'https://www.{host}/forums/-/index.rss'
        response = sess.get(rss_url, timeout=30)

        if response.status_code != 200:
            info(f"{hostname}: RSS feed returned status {response.status_code}")
            return releases

        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('item')

        if not items:
            debug(f"{hostname}: No entries found in RSS feed")
            return releases

        for item in items:
            try:
                title_tag = item.find('title')
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                if not title:
                    continue

                title = unescape(title)
                title = title.replace(']]>', '').replace('<![CDATA[', '')
                title = normalize_title_for_sonarr(title)

                item_text = item.get_text()
                thread_url = None
                match = re.search(r'https://[^\s]+/threads/[^\s]+', item_text)
                if match:
                    thread_url = match.group(0)
                if not thread_url:
                    continue

                pub_date = item.find('pubdate')
                if pub_date:
                    date_str = pub_date.get_text(strip=True)
                else:
                    # Fallback: use current time if no pubDate found
                    date_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

                mb = 0
                imdb_id = None
                password = ""

                payload = urlsafe_b64encode(
                    f"{title}|{thread_url}|{mirror}|{mb}|{password}|{imdb_id or ''}".encode("utf-8")
                ).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                releases.append({
                    "details": {
                        "title": title,
                        "hostname": hostname,
                        "imdb_id": imdb_id,
                        "link": link,
                        "mirror": mirror,
                        "size": mb * 1024 * 1024,
                        "date": date_str,
                        "source": thread_url
                    },
                    "type": "protected"
                })

            except Exception as e:
                debug(f"{hostname}: error parsing RSS entry: {e}")
                continue

    except Exception as e:
        info(f"{hostname}: RSS feed error: {e}")
        invalidate_session(shared_state)

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")
    return releases


def _search_single_page(shared_state, host, search_string, search_id, page_num, imdb_id, mirror, request_from, season,
                        episode):
    """
    Search a single page. This function is called in parallel for each page.
    """
    page_releases = []

    try:
        if page_num == 1:
            search_params = {
                'keywords': search_string,
                'c[title_only]': 1
            }
            search_url = f'https://www.{host}/search/search'
        else:
            if not search_id:
                return page_releases, None

            search_params = {
                'page': page_num,
                'q': search_string,
                'o': 'relevance'
            }
            search_url = f'https://www.{host}/search/{search_id}/'

        search_response = fetch_via_requests_session(shared_state, method="GET",
                                                     target_url=search_url,
                                                     get_params=search_params,
                                                     timeout=10)

        if search_response.status_code != 200:
            debug(f"{hostname}: [Page {page_num}] returned status {search_response.status_code}")
            return page_releases, None

        # Extract search ID from first page
        extracted_search_id = None
        if page_num == 1:
            match = re.search(r'/search/(\d+)/', search_response.url)
            if match:
                extracted_search_id = match.group(1)
                debug(f"{hostname}: [Page 1] Extracted search ID: {extracted_search_id}")

        soup = BeautifulSoup(search_response.text, 'html.parser')
        result_items = soup.select('li.block-row')

        if not result_items:
            debug(f"{hostname}: [Page {page_num}] found 0 results")
            return page_releases, extracted_search_id

        debug(f"{hostname}: [Page {page_num}] found {len(result_items)} results")

        for item in result_items:
            try:
                title_elem = item.select_one('h3.contentRow-title a')
                if not title_elem:
                    continue

                title = title_elem.get_text(separator=' ', strip=True)
                title = re.sub(r'\s+', ' ', title)
                title = unescape(title)
                title_normalized = normalize_title_for_sonarr(title)

                thread_url = title_elem.get('href')
                if thread_url.startswith('/'):
                    thread_url = f"https://www.{host}{thread_url}"

                if not shared_state.is_valid_release(title_normalized, request_from, search_string, season, episode):
                    continue

                minor_info = item.select_one('div.contentRow-minor')
                date_str = ""
                if minor_info:
                    date_elem = minor_info.select_one('time.u-dt')
                    if date_elem:
                        date_str = date_elem.get('datetime', '')

                # Fallback: use current time if no date found
                if not date_str:
                    date_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

                mb = 0
                password = ""

                payload = urlsafe_b64encode(
                    f"{title_normalized}|{thread_url}|{mirror}|{mb}|{password}|{imdb_id or ''}".encode("utf-8")
                ).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                page_releases.append({
                    "details": {
                        "title": title_normalized,
                        "hostname": hostname,
                        "imdb_id": imdb_id,
                        "link": link,
                        "mirror": mirror,
                        "size": mb * 1024 * 1024,
                        "date": date_str,
                        "source": thread_url
                    },
                    "type": "protected"
                })

            except Exception as e:
                debug(f"{hostname}: [Page {page_num}] error parsing item: {e}")

        return page_releases, extracted_search_id

    except Exception as e:
        info(f"{hostname}: [Page {page_num}] error: {e}")
        return page_releases, None


def dl_search(shared_state, start_time, request_from, search_string,
              mirror=None, season=None, episode=None):
    """
    Search with parallel pagination (max 5 pages) to find best quality releases.
    Requests are fired in parallel to minimize search time.
    """
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        title = get_localized_title(shared_state, imdb_id, 'de')
        if not title:
            info(f"{hostname}: no title for IMDb {imdb_id}")
            return releases
        search_string = title

    search_string = unescape(search_string)
    max_pages = 5

    info(
        f"{hostname}: Starting parallel paginated search for '{search_string}' (Season: {season}, Episode: {episode}) - up to {max_pages} pages")

    try:
        sess = retrieve_and_validate_session(shared_state)
        if not sess:
            info(f"Could not retrieve valid session for {host}")
            return releases

        # First, do page 1 to get the search ID
        page_1_releases, search_id = _search_single_page(
            shared_state, host, search_string, None, 1,
            imdb_id, mirror, request_from, season, episode
        )
        releases.extend(page_1_releases)

        if not search_id:
            info(f"{hostname}: Could not extract search ID, stopping pagination")
            return releases

        # Now fire remaining pages in parallel
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for page_num in range(2, max_pages + 1):
                future = executor.submit(
                    _search_single_page,
                    shared_state, host, search_string, search_id, page_num,
                    imdb_id, mirror, request_from, season, episode
                )
                futures[future] = page_num

            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    page_releases, _ = future.result()
                    releases.extend(page_releases)
                    debug(f"{hostname}: [Page {page_num}] completed with {len(page_releases)} valid releases")
                except Exception as e:
                    info(f"{hostname}: [Page {page_num}] failed: {e}")

    except Exception as e:
        info(f"{hostname}: search error: {e}")
        invalidate_session(shared_state)

    info(f"{hostname}: FINAL - Found {len(releases)} valid releases - providing to {request_from}")

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")

    return releases
