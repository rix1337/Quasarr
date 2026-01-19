# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import time
from base64 import urlsafe_b64encode
from html import unescape
from urllib.parse import urljoin, quote_plus

from bs4 import BeautifulSoup

from quasarr.downloads.sources.al import (guess_title,
                                          parse_info_from_feed_entry, parse_info_from_download_item)
from quasarr.providers.hostname_issues import mark_hostname_issue, clear_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import info, debug
from quasarr.providers.sessions.al import invalidate_session, fetch_via_requests_session

hostname = "al"
supported_mirrors = ["rapidgator", "ddownload"]


def convert_to_rss_date(date_str: str) -> str:
    parsed = datetime.strptime(date_str, "%d.%m.%Y - %H:%M")
    return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")


import re
from datetime import datetime, timedelta


def convert_to_rss_date(date_str: str) -> str:
    # First try to parse relative dates (German and English)
    parsed_date = parse_relative_date(date_str)
    if parsed_date:
        return parsed_date.strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Fall back to absolute date parsing
    try:
        parsed = datetime.strptime(date_str, "%d.%m.%Y - %H:%M")
        return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except ValueError:
        # If parsing fails, return the original string or handle as needed
        raise ValueError(f"Could not parse date: {date_str}")


def parse_relative_date(raw: str) -> datetime | None:
    # German pattern: "vor X Einheit(en)"
    german_match = re.match(r"vor\s+(\d+)\s+(\w+)", raw, re.IGNORECASE)
    if german_match:
        num = int(german_match.group(1))
        unit = german_match.group(2).lower()

        if unit.startswith("sekunde"):
            delta = timedelta(seconds=num)
        elif unit.startswith("minute"):
            delta = timedelta(minutes=num)
        elif unit.startswith("stunde"):
            delta = timedelta(hours=num)
        elif unit.startswith("tag"):
            delta = timedelta(days=num)
        elif unit.startswith("woche"):
            delta = timedelta(weeks=num)
        elif unit.startswith("monat"):
            delta = timedelta(days=30 * num)
        elif unit.startswith("jahr"):
            delta = timedelta(days=365 * num)
        else:
            return None

        return datetime.utcnow() - delta

    # English pattern: "X Unit(s) ago"
    english_match = re.match(r"(\d+)\s+(\w+)\s+ago", raw, re.IGNORECASE)
    if english_match:
        num = int(english_match.group(1))
        unit = english_match.group(2).lower()

        # Remove plural 's' if present
        if unit.endswith('s'):
            unit = unit[:-1]

        if unit.startswith("second"):
            delta = timedelta(seconds=num)
        elif unit.startswith("minute"):
            delta = timedelta(minutes=num)
        elif unit.startswith("hour"):
            delta = timedelta(hours=num)
        elif unit.startswith("day"):
            delta = timedelta(days=num)
        elif unit.startswith("week"):
            delta = timedelta(weeks=num)
        elif unit.startswith("month"):
            delta = timedelta(days=30 * num)
        elif unit.startswith("year"):
            delta = timedelta(days=365 * num)
        else:
            return None

        return datetime.utcnow() - delta

    return None


def extract_size(text):
    match = re.match(r"(\d+(\.\d+)?) ([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(3)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def get_release_id(tag):
    match = re.search(r"release\s+(\d+):", tag.get_text(strip=True), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def al_feed(shared_state, start_time, request_from, mirror=None):
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    if not "arr" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    if "Radarr" in request_from:
        wanted_type = "movie"
    else:
        wanted_type = "series"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by {hostname}.')
        return releases

    try:
        r = fetch_via_requests_session(shared_state, method="GET", target_url=f'https://www.{host}/', timeout=30)
        r.raise_for_status()
    except Exception as e:
        info(f"{hostname}: could not fetch feed: {e}")
        mark_hostname_issue(hostname, "feed", str(e) if "e" in dir() else "Error occurred")
        invalidate_session(shared_state)
        return releases

    soup = BeautifulSoup(r.content, 'html.parser')

    # 1) New “Releases”
    release_rows = soup.select("#releases_updates_list table tbody tr")
    # 2) New “Episodes”
    episode_rows = soup.select("#episodes_updates_list table tbody tr")
    # 3) “Upgrades” Releases
    upgrade_rows = soup.select("#releases_modified_updates_list table tbody tr")

    for tr in release_rows + episode_rows + upgrade_rows:
        try:
            p_tag = tr.find("p")
            if not p_tag:
                continue
            a_tag = p_tag.find("a", href=True)
            if not a_tag:
                continue

            url = a_tag["href"].strip()
            # Prefer data-original-title, fall back to title, then to inner text
            if a_tag.get("data-original-title"):
                raw_base_title = a_tag["data-original-title"]
            elif a_tag.get("title"):
                raw_base_title = a_tag["title"]
            else:
                raw_base_title = a_tag.get_text(strip=True)

            release_type = None
            label_div = tr.find("div", class_="label-group")
            if label_div:
                for lbl in label_div.find_all("a", href=True):
                    href = lbl["href"].rstrip("/").lower()
                    if href.endswith("/anime-series"):
                        release_type = "series"
                        break
                    elif href.endswith("/anime-movies"):
                        release_type = "movie"
                        break

            if release_type is None or release_type != wanted_type:
                continue

            date_converted = ""
            small_tag = tr.find("small", class_="text-muted")
            if small_tag:
                raw_date_str = small_tag.get_text(strip=True)
                if raw_date_str.startswith("vor"):
                    dt = parse_relative_date(raw_date_str)
                    if dt:
                        date_converted = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
                else:
                    try:
                        date_converted = convert_to_rss_date(raw_date_str)
                    except Exception as e:
                        debug(f"{hostname}: could not parse date '{raw_date_str}': {e}")

            # Each of these signifies an individual release block
            mt_blocks = tr.find_all("div", class_="mt10")
            for block in mt_blocks:
                release_id = get_release_id(block)
                release_info = parse_info_from_feed_entry(block, raw_base_title, release_type)
                final_title = guess_title(shared_state, raw_base_title, release_info)

                # Build payload using final_title
                mb = 0  # size not available in feed
                raw = f"{final_title}|{url}|{mirror}|{mb}|{release_id}||{hostname}".encode("utf-8")
                payload = urlsafe_b64encode(raw).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                # Append only unique releases
                if final_title not in [r["details"]["title"] for r in releases]:
                    releases.append({
                        "details": {
                            "title": final_title,
                            "hostname": hostname,
                            "imdb_id": None,
                            "link": link,
                            "mirror": mirror,
                            "size": mb * 1024 * 1024,
                            "date": date_converted,
                            "source": url
                        },
                        "type": "protected"
                    })

        except Exception as e:
            info(f"{hostname}: error parsing feed item: {e}")
            mark_hostname_issue(hostname, "feed", str(e) if "e" in dir() else "Error occurred")

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases


def extract_season(title: str) -> int | None:
    match = re.search(r'(?i)(?:^|[^a-zA-Z0-9])S(\d{1,4})(?!\d)', title)
    if match:
        return int(match.group(1))
    return None


def al_search(shared_state, start_time, request_from, search_string,
              mirror=None, season=None, episode=None):
    releases = []
    host = shared_state.values["config"]("Hostnames").get(hostname)

    if not "arr" in request_from.lower():
        debug(f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!')
        return releases

    if "Radarr" in request_from:
        valid_type = "movie"
    else:
        valid_type = "series"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by {hostname}.')
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)
    if imdb_id:
        title = get_localized_title(shared_state, imdb_id, 'de')
        if not title:
            info(f"{hostname}: no title for IMDb {imdb_id}")
            return releases
        search_string = title

    search_string = unescape(search_string)

    encoded_search_string = quote_plus(search_string)

    try:
        url = f'https://www.{host}/search?q={encoded_search_string}'
        r = fetch_via_requests_session(shared_state, method="GET", target_url=url, timeout=10)
        r.raise_for_status()
    except Exception as e:
        info(f"{hostname}: search load error: {e}")
        mark_hostname_issue(hostname, "search", str(e) if "e" in dir() else "Error occurred")
        invalidate_session(shared_state)
        return releases

    if r.history:
        # If just one valid search result exists, AL skips the search result page
        last_redirect = r.history[-1]
        redirect_location = last_redirect.headers['Location']
        absolute_redirect_url = urljoin(last_redirect.url, redirect_location)  # in case of relative URL
        debug(f"{search_string} redirected to {absolute_redirect_url} instead of search results page")

        try:
            soup = BeautifulSoup(r.text, "html.parser")
            page_title = soup.title.string
        except:
            page_title = ""

        results = [{"url": absolute_redirect_url, "title": page_title}]
    else:
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []

        for panel in soup.select('div.panel.panel-default'):
            body = panel.find('div', class_='panel-body')
            if not body:
                continue

            title_tag = body.select_one('h4.title-list a[href]')
            if not title_tag:
                continue
            url = title_tag['href'].strip()
            name = title_tag.get_text(strip=True)

            sanitized_search_string = shared_state.sanitize_string(search_string)
            sanitized_title = shared_state.sanitize_string(name)
            if not sanitized_search_string in sanitized_title:
                debug(f"Search string '{search_string}' doesn't match '{name}'")
                continue
            debug(f"Matched search string '{search_string}' with result '{name}'")

            type_label = None
            for lbl in body.select('div.label-group a[href]'):
                href = lbl['href']
                if '/anime-series' in href:
                    type_label = 'series'
                    break
                if '/anime-movies' in href:
                    type_label = 'movie'
                    break

            if not type_label or type_label != valid_type:
                continue

            results.append({"url": url, "title": name})

    for result in results:
        try:
            url = result["url"]
            title = result.get("title") or ""

            context = "recents_al"
            threshold = 60
            recently_searched = shared_state.get_recently_searched(shared_state, context, threshold)
            entry = recently_searched.get(url, {})
            ts = entry.get("timestamp")
            use_cache = ts and ts > datetime.now() - timedelta(seconds=threshold)

            if use_cache and entry.get("html"):
                debug(f"Using cached content for '{url}'")
                data_html = entry["html"]
            else:
                entry = {"timestamp": datetime.now()}
                data_html = fetch_via_requests_session(shared_state, method="GET", target_url=url, timeout=10).text

            entry["html"] = data_html
            recently_searched[url] = entry
            shared_state.update(context, recently_searched)

            content = BeautifulSoup(data_html, "html.parser")

            # Find each download‐table and process it
            release_id = 0
            download_tabs = content.select("div[id^=download_]")
            for tab in download_tabs:
                release_id += 1

                release_info = parse_info_from_download_item(tab, content, page_title=title,
                                                             release_type=valid_type, requested_episode=episode)

                # Parse date
                date_td = tab.select_one("tr:has(th>i.fa-calendar-alt) td.modified")
                if date_td:
                    raw_date = date_td.get_text(strip=True)
                    try:
                        dt = datetime.strptime(raw_date, "%d.%m.%Y %H:%M")
                        date_str = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
                    except Exception:
                        date_str = ""
                else:
                    date_str = (datetime.utcnow() - timedelta(hours=1)) \
                        .strftime("%a, %d %b %Y %H:%M:%S +0000")

                # Parse filesize from the <tr> with <i class="fa-hdd">
                size_td = tab.select_one("tr:has(th>i.fa-hdd) td")
                mb = 0
                if size_td:
                    size_text = size_td.get_text(strip=True)
                    candidates = re.findall(r'(\d+(\.\d+)?\s*[A-Za-z]+)', size_text)
                    if candidates:
                        size_string = candidates[-1][0]
                        try:
                            size_item = extract_size(size_string)
                            mb = shared_state.convert_to_mb(size_item)
                        except Exception as e:
                            debug(f"Error extracting size for {title}: {e}")

                if episode:
                    try:
                        total_episodes = release_info.episode_max
                        if total_episodes:
                            if mb > 0:
                                mb = int(mb / total_episodes)
                            # Overwrite values so guessing the title only applies the requested episode
                            release_info.episode_min = int(episode)
                            release_info.episode_max = int(episode)
                        else:  # if no total episode count - assume the requested episode is missing in the release
                            continue
                    except ValueError:
                        pass

                # If no valid title was grabbed from Release Notes, guess the title
                if release_info.release_title:
                    release_title = release_info.release_title
                else:
                    release_title = guess_title(shared_state, title, release_info)

                if season and release_info.season != int(season):
                    debug(f"Excluding {release_title} due to season mismatch: {release_info.season} != {season}")
                    continue

                payload = urlsafe_b64encode(
                    f"{release_title}|{url}|{mirror}|{mb}|{release_id}|{imdb_id or ''}"
                    .encode("utf-8")
                ).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"

                releases.append({
                    "details": {
                        "title": release_title,
                        "hostname": hostname,
                        "imdb_id": imdb_id,
                        "link": link,
                        "mirror": mirror,
                        "size": mb * 1024 * 1024,
                        "date": date_str,
                        "source": f"{url}#download_{release_id}"
                    },
                    "type": "protected"
                })

        except Exception as e:
            info(f"{hostname}: error parsing search item: {e}")
            mark_hostname_issue(hostname, "search", str(e) if "e" in dir() else "Error occurred")

    elapsed = time.time() - start_time
    debug(f"Time taken: {elapsed:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases
