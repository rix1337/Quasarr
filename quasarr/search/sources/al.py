# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import time
from html import unescape
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_ANIME,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.downloads.sources.al import (
    _guess_title,
    _parse_info_from_download_item,
    _parse_info_from_feed_entry,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, error, info, trace, warn
from quasarr.providers.sessions.al import fetch_via_requests_session, invalidate_session
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    get_base_search_category_id,
    get_recently_searched,
    is_imdb_id,
    sanitize_string,
)
from quasarr.providers.xem_metadata import get_season_name
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "al"
    language = "de"
    requires_account = True
    requires_flaresolverr = True
    supports_imdb = True
    supports_phrase = False
    supports_absolute_numbering = True
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS, SEARCH_CAT_SHOWS_ANIME]
    requires_login = True

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        releases = []

        host = shared_state.values["config"]("Hostnames").get(self.initials)

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_MOVIES:
            wanted_type = "movie"
        elif base_search_category == SEARCH_CAT_SHOWS:
            wanted_type = "series"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        try:
            r = fetch_via_requests_session(
                shared_state,
                method="GET",
                target_url=f"https://www.{host}/",
                timeout=FEED_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
        except Exception as e:
            error(f"Could not fetch feed: {e}")
            mark_hostname_issue(
                self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
            )
            invalidate_session(shared_state)
            return releases

        soup = BeautifulSoup(r.content, "html.parser")

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
                        dt = _parse_relative_date(raw_date_str)
                        if dt:
                            date_converted = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
                    else:
                        try:
                            date_converted = _convert_to_rss_date(raw_date_str)
                        except Exception as e:
                            debug(f"Could not parse date '{raw_date_str}': {e}")

                # Each of these signifies an individual release block
                mt_blocks = tr.find_all("div", class_="mt10")
                for block in mt_blocks:
                    release_id = _get_release_id(block)
                    release_info = _parse_info_from_feed_entry(
                        block, raw_base_title, release_type
                    )
                    final_title = _guess_title(raw_base_title, release_info)

                    # Build payload using final_title
                    mb = 0  # size not available in feed
                    link = generate_download_link(
                        shared_state,
                        final_title,
                        url,
                        mb,
                        release_id,
                        None,
                        self.initials,
                    )

                    # Append only unique releases
                    if final_title not in [r["details"]["title"] for r in releases]:
                        releases.append(
                            {
                                "details": {
                                    "title": final_title,
                                    "hostname": self.initials,
                                    "imdb_id": None,
                                    "link": link,
                                    "size": mb * 1024 * 1024,
                                    "date": date_converted,
                                    "source": url,
                                },
                                "type": "protected",
                            }
                        )

            except Exception as e:
                info(f"Error parsing feed item: {e}")
                mark_hostname_issue(
                    self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
                )

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases

    def search(
        self,
        shared_state: shared_state,
        start_time: float,
        search_category: str,
        search_string: str = "",
        season: int = None,
        episode: int = None,
    ) -> list[SearchRelease]:
        releases = []

        host = shared_state.values["config"]("Hostnames").get(self.initials)

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_MOVIES:
            valid_type = "movie"
        elif base_search_category == SEARCH_CAT_SHOWS:
            valid_type = "series"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            title = get_localized_title(shared_state, imdb_id, "de")
            if not title:
                info(f"No title for IMDb {imdb_id}")
                return releases
            search_string = title

        search_string = unescape(search_string)

        season_title = None
        xem_name = None
        if season:
            season_title = f"{search_string} Staffel {season}"
            xem_name = get_season_name(search_string, season)

        results = []
        for variant in [
            season_title,
            xem_name,
            search_string,
        ]:
            if results:
                break
            if variant is None:
                continue

            encoded_search_string = quote_plus(variant)
            year = None
            if imdb_id is not None and variant == search_string:
                year = get_year(imdb_id)

            try:
                url = f"https://www.{host}/search?q={encoded_search_string}"
                r = fetch_via_requests_session(
                    shared_state,
                    method="GET",
                    target_url=url,
                    timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                    year=year,
                )
                r.raise_for_status()
            except Exception as e:
                info(f"Search load error: {e}")
                mark_hostname_issue(
                    self.initials,
                    "search",
                    str(e) if "e" in dir() else "Error occurred",
                )
                invalidate_session(shared_state)
                continue

            # If just one valid search result exists, AL skips the search result page
            if r.history:
                last_redirect = r.history[-1]
                redirect_location = last_redirect.headers["Location"]
                absolute_redirect_url = urljoin(
                    last_redirect.url, redirect_location
                )  # in case of relative URL
                debug(
                    f"<y>{variant}</y> redirected to <d>{absolute_redirect_url}</d> instead of search results page"
                )

                try:
                    soup = BeautifulSoup(r.text, "html.parser")
                    page_title = soup.title.string
                except:
                    page_title = ""

                results.append({"url": absolute_redirect_url, "title": page_title})
                continue

            soup = BeautifulSoup(r.text, "html.parser")

            for panel in soup.select("div.panel.panel-default"):
                body = panel.find("div", class_="panel-body")
                if not body:
                    continue

                title_tag = body.select_one("h4.title-list a[href]")
                if not title_tag:
                    continue
                url = title_tag["href"].strip()
                name = title_tag.get_text(strip=True)

                sanitized_search_string = sanitize_string(search_string)
                sanitized_title = sanitize_string(name)
                if not sanitized_search_string in sanitized_title:
                    debug(f"Search string '{search_string}' doesn't match '{name}'")
                    continue
                trace(f"Matched search string '{search_string}' with result '{name}'")

                type_label = None
                for lbl in body.select("div.label-group a[href]"):
                    href = lbl["href"]
                    if "/anime-series" in href:
                        type_label = "series"
                        break
                    if "/anime-movies" in href:
                        type_label = "movie"
                        break

                if not type_label or type_label != valid_type:
                    continue

                results.append({"url": url, "title": name})

        for result in results:
            try:
                url = result["url"]
                title = result.get("title") or ""
                trace(
                    f"query='{search_string}' season={season} "
                    f"episode={episode} result_title='{title}' url='{url}'"
                )

                context = "recents_al"
                threshold = 60
                recently_searched = get_recently_searched(
                    shared_state, context, threshold
                )
                entry = recently_searched.get(url, {})
                ts = entry.get("timestamp")
                use_cache = ts and ts > datetime.now() - timedelta(seconds=threshold)

                if use_cache and entry.get("html"):
                    debug(f"Using cached content for <d>{url}</d>")
                    data_html = entry["html"]
                else:
                    entry = {"timestamp": datetime.now()}
                    data_html = fetch_via_requests_session(
                        shared_state,
                        method="GET",
                        target_url=url,
                        timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
                    ).text

                entry["html"] = data_html
                recently_searched[url] = entry
                shared_state.update(context, recently_searched)

                content = BeautifulSoup(data_html, "html.parser")

                # Find each download‐table and process it
                release_id = 0
                download_tabs = content.select("div[id^=download_]")
                for tab in download_tabs:
                    release_id += 1

                    release_info = _parse_info_from_download_item(
                        tab,
                        content,
                        page_title=title,
                        release_type=valid_type,
                        requested_season=True if season else False,
                        requested_episode=episode,
                    )
                    trace(
                        f"tab={tab.get('id')} release_id={release_id} "
                        f"parsed_release_title='{release_info.release_title}' "
                        f"parsed_season={release_info.season} "
                        f"parsed_episode_min={release_info.episode_min} "
                        f"parsed_episode_max={release_info.episode_max}"
                    )

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
                        date_str = (datetime.utcnow() - timedelta(hours=1)).strftime(
                            "%a, %d %b %Y %H:%M:%S +0000"
                        )

                    # Parse filesize from the <tr> with <i class="fa-hdd">
                    size_td = tab.select_one("tr:has(th>i.fa-hdd) td")
                    mb = 0
                    if size_td:
                        size_text = size_td.get_text(strip=True)
                        candidates = re.findall(r"(\d+(\.\d+)?\s*[A-Za-z]+)", size_text)
                        if candidates:
                            size_string = candidates[-1][0]
                            try:
                                size_item = _extract_size(size_string)
                                mb = convert_to_mb(size_item)
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
                        title_source = "release_notes"
                    else:
                        release_title = _guess_title(title, release_info)
                        title_source = "guessed"
                    trace(
                        f"chosen_title_source={title_source} "
                        f"final_release_title='{release_title}'"
                    )

                    if season and release_info.season != int(season):
                        trace(
                            f"Excluding {release_title} due to season mismatch: {release_info.season} != {season}"
                        )
                        continue

                    link = generate_download_link(
                        shared_state,
                        release_title,
                        url,
                        mb,
                        release_id,
                        imdb_id or "",
                        self.initials,
                    )

                    releases.append(
                        {
                            "details": {
                                "title": release_title,
                                "hostname": self.initials,
                                "imdb_id": imdb_id,
                                "link": link,
                                "size": mb * 1024 * 1024,
                                "date": date_str,
                                "source": f"{url}#download_{release_id}",
                            },
                            "type": "protected",
                        }
                    )

            except Exception as e:
                info(f"Error parsing search item: {e}")
                mark_hostname_issue(
                    self.initials,
                    "search",
                    str(e) if "e" in dir() else "Error occurred",
                )

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


import re
from datetime import datetime, timedelta


def _convert_to_rss_date(date_str: str) -> str:
    # First try to parse relative dates (German and English)
    parsed_date = _parse_relative_date(date_str)
    if parsed_date:
        return parsed_date.strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Fall back to absolute date parsing
    try:
        parsed = datetime.strptime(date_str, "%d.%m.%Y - %H:%M")
        return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except ValueError as e:
        # If parsing fails, return the original string or handle as needed
        raise ValueError(f"Could not parse date: {date_str}") from e


def _parse_relative_date(raw: str) -> datetime | None:
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
        if unit.endswith("s"):
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


def _extract_size(text):
    match = re.match(r"(\d+(\.\d+)?) ([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(3)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def _get_release_id(tag):
    match = re.search(r"release\s+(\d+):", tag.get_text(strip=True), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0
