# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta

import requests

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title
from quasarr.providers.log import debug, info

hostname = "sf"
supported_mirrors = ["1fichier", "ddownload", "katfile", "rapidgator", "turbobit"]

from bs4 import BeautifulSoup

check = lambda s: s.replace(
    "".join(chr((ord(c) - 97 - 7) % 26 + 97) for c in "ylhr"),
    "".join(chr((ord(c) - 97 - 7) % 26 + 97) for c in "hu"),
)


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
            "1F": "1fichier",
            "DD": "ddownload",
            "KA": "katfile",
            "RG": "rapidgator",
            "TB": "turbobit",
        }

        h3 = entry.select_one("h3")
        name = h3.get_text(separator=" ", strip=True) if h3 else ""

        season = {}
        for a in entry.select("a.dlb.row"):
            if a.find_parent("div.list.simple"):
                continue
            host = a.get_text(strip=True)
            if len(host) > 2:  # episode hosts are 2 chars
                season[host] = f"{base_url}{a['href']}"

        # fallback: if mirrors are falsely missing a mirror title, return first season link as "filecrypt"
        if not season:
            fallback = next(
                (
                    a
                    for a in entry.select("a.dlb.row")
                    if not a.find_parent("div.list.simple")
                ),
                None,
            )
            if fallback:
                season["filecrypt"] = f"{base_url}{fallback['href']}"

        episodes = []
        for ep_row in entry.select("div.list.simple > div.row"):
            if "head" in ep_row.get("class", []):
                continue

            divs = ep_row.find_all("div", recursive=False)
            number = int(divs[0].get_text(strip=True).rstrip("."))
            title = divs[1].get_text(strip=True)

            ep_links = {}
            for a in ep_row.select("div.row > a.dlb.row"):
                host = a.get_text(strip=True)
                full_host = host_map.get(host, host)
                ep_links[full_host] = f"{base_url}{a['href']}"

            episodes.append({"number": number, "title": title, "links": ep_links})

        mirrors = {"name": name, "season": season, "episodes": episodes}
    except Exception as e:
        info(f"Error parsing mirrors: {e}")
        mark_hostname_issue(
            hostname, "feed", str(e) if "e" in dir() else "Error occurred"
        )

    return mirrors


def sf_feed(shared_state, start_time, request_from, mirror=None):
    releases = []
    sf = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = check(sf)

    if not "sonarr" in request_from.lower():
        debug(
            f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!'
        )
        return releases

    if mirror and mirror not in supported_mirrors:
        debug(
            f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
            " Skipping search!"
        )
        return releases

    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    date = datetime.now()
    days_to_cover = 2

    while days_to_cover > 0:
        days_to_cover -= 1
        formatted_date = date.strftime("%Y-%m-%d")
        date -= timedelta(days=1)

        try:
            r = requests.get(
                f"https://{sf}/updates/{formatted_date}#list", headers, timeout=30
            )
            r.raise_for_status()
        except Exception as e:
            info(f"Error loading {hostname.upper()} feed: {e} for {formatted_date}")
            mark_hostname_issue(
                hostname, "feed", str(e) if "e" in dir() else "Error occurred"
            )
            return releases

        content = BeautifulSoup(r.text, "html.parser")
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
                            f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}|{hostname}".encode(
                                "utf-8"
                            )
                        ).decode("utf-8")
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
                info(f"Error parsing {hostname.upper()} feed: {e}")
                mark_hostname_issue(
                    hostname, "feed", str(e) if "e" in dir() else "Error occurred"
                )

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases


def extract_size(text):
    match = re.match(r"(\d+(\.\d+)?) ([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(3)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def sf_search(
    shared_state,
    start_time,
    request_from,
    search_string,
    mirror=None,
    season=None,
    episode=None,
):
    releases = []
    sf = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = check(sf)

    imdb_id_in_search = shared_state.is_imdb_id(search_string)
    if imdb_id_in_search:
        search_string = get_localized_title(shared_state, imdb_id_in_search, "de")
        if not search_string:
            info(f"Could not extract title from IMDb-ID {imdb_id_in_search}")
            return releases
        search_string = html.unescape(search_string)

    if not "sonarr" in request_from.lower():
        debug(
            f'Skipping {request_from} search on "{hostname.upper()}" (unsupported media type)!'
        )
        return releases

    if mirror and mirror not in supported_mirrors:
        debug(
            f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported: {supported_mirrors}.'
        )
        return releases

    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    # search API
    url = f"https://{sf}/api/v2/search?q={search_string}&ql=DE"
    headers = {"User-Agent": shared_state.values["user_agent"]}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        feed = r.json()
    except Exception as e:
        info(f"Error loading {hostname.upper()} search: {e}")
        mark_hostname_issue(
            hostname, "search", str(e) if "e" in dir() else "Error occurred"
        )
        return releases

    results = feed.get("result", [])
    for result in results:
        sanitized_search_string = shared_state.sanitize_string(search_string)
        sanitized_title = shared_state.sanitize_string(result.get("title", ""))
        if not re.search(rf"\b{re.escape(sanitized_search_string)}\b", sanitized_title):
            debug(
                f"Search string '{search_string}' doesn't match '{result.get('title')}'"
            )
            continue
        debug(
            f"Matched search string '{search_string}' with result '{result.get('title')}'"
        )

        series_id = result.get("url_id")
        context = "recents_sf"
        threshold = 60
        recently_searched = shared_state.get_recently_searched(
            shared_state, context, threshold
        )
        entry = recently_searched.get(series_id, {})
        ts = entry.get("timestamp")
        use_cache = ts and ts > datetime.now() - timedelta(seconds=threshold)

        if use_cache and entry.get("content"):
            debug(f"Using cached content for '/{series_id}'")
            data_html = entry["content"]
            imdb_cached = entry.get("imdb_id")
            if imdb_cached:
                imdb_id = imdb_cached
            content = BeautifulSoup(data_html, "html.parser")
        else:
            # fresh fetch: record timestamp
            entry = {"timestamp": datetime.now()}

            # load series page
            series_url = f"https://{sf}/{series_id}"
            try:
                r = requests.get(series_url, headers=headers, timeout=10)
                r.raise_for_status()
                series_page = r.text
                imdb_link = BeautifulSoup(series_page, "html.parser").find(
                    "a", href=re.compile(r"imdb\.com")
                )
                imdb_id = (
                    re.search(r"tt\d+", str(imdb_link)).group() if imdb_link else None
                )
                season_id = re.findall(r"initSeason\('(.+?)\',", series_page)[0]
            except Exception as e:
                debug(f"Failed to load or parse series page for {series_id}")
                mark_hostname_issue(hostname, "search", str(e))
                continue

            # fetch API HTML
            epoch = str(datetime.now().timestamp()).replace(".", "")[:-3]
            api_url = f"https://{sf}/api/v1/{season_id}/season/ALL?lang=ALL&_={epoch}"
            debug(f"Requesting SF API URL: {api_url}")
            try:
                r = requests.get(api_url, headers=headers, timeout=10)
                r.raise_for_status()
                resp_json = r.json()
                if resp_json.get("error"):
                    info(
                        f"SF API error for series '{series_id}' at URL {api_url}: {resp_json.get('message')}"
                    )
                    continue
                data_html = resp_json.get("html", "")
            except Exception as e:
                info(f"Error loading SF API for {series_id} at {api_url}: {e}")
                mark_hostname_issue(
                    hostname, "search", str(e) if "e" in dir() else "Error occurred"
                )
                continue

            # cache content and imdb_id
            entry["content"] = data_html
            entry["imdb_id"] = imdb_id
            recently_searched[series_id] = entry
            shared_state.update(context, recently_searched)
            content = BeautifulSoup(data_html, "html.parser")

        # parse episodes/releases
        for item in content.find_all("h3"):
            try:
                details = item.parent.parent.parent
                title = details.find("small").text.strip()

                mirrors = parse_mirrors(f"https://{sf}", details)
                source = (
                    mirror
                    and mirrors["season"].get(mirror)
                    or next(iter(mirrors["season"].values()), None)
                )
                if not source:
                    debug(f"No source mirror found for {title}")
                    continue

                try:
                    size_string = (
                        item.find("span", {"class": "morespec"})
                        .text.split("|")[1]
                        .strip()
                    )
                    size_item = extract_size(size_string)
                    mb = shared_state.convert_to_mb(size_item)
                except Exception as e:
                    debug(f"Error extracting size for {title}: {e}")
                    mb = 0

                if episode:
                    try:
                        if not re.search(r"S\d{1,3}E\d{1,3}", title):
                            episodes_in_release = len(mirrors["episodes"])

                            # Get the correct episode entry (episode numbers are 1-based, list index is 0-based)
                            episode_data = next(
                                (
                                    e
                                    for e in mirrors["episodes"]
                                    if e["number"] == int(episode)
                                ),
                                None,
                            )

                            if episode_data:
                                title = re.sub(
                                    r"(S\d{1,3})", rf"\1E{episode:02d}", title
                                )
                                if mirror:
                                    if mirror not in episode_data["links"]:
                                        debug(
                                            f"Mirror '{mirror}' does not exist for '{title}' episode {episode}'"
                                        )
                                    else:
                                        source = episode_data["links"][mirror]

                                else:
                                    source = next(iter(episode_data["links"].values()))
                            else:
                                debug(
                                    f"Episode '{episode}' data not found in mirrors for '{title}'"
                                )

                            if episodes_in_release:
                                try:
                                    mb = shared_state.convert_to_mb(
                                        {
                                            "size": float(size_item["size"])
                                            // episodes_in_release,
                                            "sizeunit": size_item["sizeunit"],
                                        }
                                    )
                                except Exception as e:
                                    debug(f"Error calculating size for {title}: {e}")
                                    mb = 0
                    except:
                        continue

                # check down here on purpose, because the title may be modified at episode stage
                if not shared_state.is_valid_release(
                    title, request_from, search_string, season, episode
                ):
                    continue

                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}|{hostname}".encode()
                ).decode()
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                size_bytes = mb * 1024 * 1024

                releases.append(
                    {
                        "details": {
                            "title": title,
                            "hostname": hostname.lower(),
                            "imdb_id": imdb_id,
                            "link": link,
                            "mirror": mirror,
                            "size": size_bytes,
                            "date": one_hour_ago,
                            "source": f"https://{sf}/{series_id}/{season}"
                            if season
                            else f"https://{sf}/{series_id}",
                        },
                        "type": "protected",
                    }
                )
            except Exception as e:
                debug(f"Error parsing item for '{search_string}': {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f}s ({hostname})")

    if releases:
        clear_hostname_issue(hostname)
    return releases
