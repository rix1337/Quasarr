# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
from datetime import datetime, timedelta
from json import dumps, loads
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import debug, info


def _get_db(table_name):
    """Lazy import to avoid circular dependency."""
    from quasarr.storage.sqlite_database import DataBase

    return DataBase(table_name)


def _get_config(section):
    """Lazy import to avoid circular dependency."""
    from quasarr.storage.config import Config

    return Config(section)


class TitleCleaner:
    @staticmethod
    def sanitize(title):
        if not title:
            return ""
        sanitized_title = html.unescape(title)
        sanitized_title = re.sub(
            r"[^a-zA-Z0-9äöüÄÖÜß&-']", " ", sanitized_title
        ).strip()
        sanitized_title = sanitized_title.replace(" - ", "-")
        sanitized_title = re.sub(r"\s{2,}", " ", sanitized_title)
        return sanitized_title

    @staticmethod
    def clean(title):
        try:
            # Regex to find the title part before common release tags
            pattern = r"(.*?)(?:[\.\s](?!19|20)\d{2}|[\.\s]German|[\.\s]GERMAN|[\.\s]\d{3,4}p|[\.\s]S(?:\d{1,3}))"
            match = re.search(pattern, title)
            if match:
                extracted_title = match.group(1)
            else:
                extracted_title = title

            tags_to_remove = [
                r"[\.\s]UNRATED.*",
                r"[\.\s]Unrated.*",
                r"[\.\s]Uncut.*",
                r"[\.\s]UNCUT.*",
                r"[\.\s]Directors[\.\s]Cut.*",
                r"[\.\s]Final[\.\s]Cut.*",
                r"[\.\s]DC.*",
                r"[\.\s]REMASTERED.*",
                r"[\.\s]EXTENDED.*",
                r"[\.\s]Extended.*",
                r"[\.\s]Theatrical.*",
                r"[\.\s]THEATRICAL.*",
            ]

            clean_title = extracted_title
            for tag in tags_to_remove:
                clean_title = re.sub(tag, "", clean_title, flags=re.IGNORECASE)

            clean_title = clean_title.replace(".", " ").strip()
            clean_title = re.sub(r"\s+", " ", clean_title)
            clean_title = clean_title.replace(" ", "+")

            return clean_title
        except Exception as e:
            debug(f"Error cleaning title '{title}': {e}")
            return title


class IMDbAPI:
    """Tier 1: api.imdbapi.dev - Primary, fast, comprehensive."""

    BASE_URL = "https://api.imdbapi.dev"

    @staticmethod
    def get_title(imdb_id):
        try:
            response = requests.get(f"{IMDbAPI.BASE_URL}/titles/{imdb_id}", timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            info(f"IMDbAPI get_title failed for {imdb_id}: {e}")
            return None

    @staticmethod
    def get_akas(imdb_id):
        try:
            response = requests.get(
                f"{IMDbAPI.BASE_URL}/titles/{imdb_id}/akas", timeout=30
            )
            response.raise_for_status()
            return response.json().get("akas", [])
        except Exception as e:
            info(f"IMDbAPI get_akas failed for {imdb_id}: {e}")
            return []

    @staticmethod
    def search_titles(query):
        try:
            response = requests.get(
                f"{IMDbAPI.BASE_URL}/search/titles?query={quote(query)}&limit=5",
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("titles", [])
        except Exception as e:
            debug(f"IMDbAPI search_titles failed: {e}")
            return []


class IMDbCDN:
    """Tier 2: v2.sg.media-imdb.com - Fast fallback for English data."""

    CDN_URL = "https://v2.sg.media-imdb.com/suggestion"

    @staticmethod
    def _get_cdn_data(imdb_id, language, user_agent):
        try:
            if not imdb_id or len(imdb_id) < 2:
                return None

            headers = {
                "Accept-Language": f"{language},en;q=0.9",
                "User-Agent": user_agent,
                "Accept": "application/json",
            }

            first_char = imdb_id[0].lower()
            url = f"{IMDbCDN.CDN_URL}/{first_char}/{imdb_id}.json"

            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()

            data = response.json()

            if "d" in data and len(data["d"]) > 0:
                for entry in data["d"]:
                    if entry.get("id") == imdb_id:
                        return entry
                return data["d"][0]

        except Exception as e:
            debug(f"IMDbCDN request failed for {imdb_id}: {e}")

        return None

    @staticmethod
    def get_poster(imdb_id, user_agent):
        data = IMDbCDN._get_cdn_data(imdb_id, "en", user_agent)
        if data:
            image_node = data.get("i")
            if image_node and "imageUrl" in image_node:
                return image_node["imageUrl"]
        return None

    @staticmethod
    def get_title(imdb_id, user_agent):
        """Returns the English title from CDN."""
        data = IMDbCDN._get_cdn_data(imdb_id, "en", user_agent)
        if data and "l" in data:
            return data["l"]
        return None

    @staticmethod
    def search_titles(query, ttype, language, user_agent):
        try:
            clean_query = quote(query.lower().replace(" ", "_"))
            if not clean_query:
                return []

            headers = {
                "Accept-Language": f"{language},en;q=0.9",
                "User-Agent": user_agent,
            }

            first_char = clean_query[0]
            url = f"{IMDbCDN.CDN_URL}/{first_char}/{clean_query}.json"

            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                results = []
                if "d" in data:
                    for item in data["d"]:
                        results.append(
                            {
                                "id": item.get("id"),
                                "titleNameText": item.get("l"),
                                "titleReleaseText": item.get("y"),
                            }
                        )
                return results

        except Exception as e:
            from quasarr.providers.log import debug

            debug(f"IMDb CDN search failed: {e}")

        return []


class IMDbFlareSolverr:
    """Tier 3: FlareSolverr - Robust fallback using browser automation."""

    WEB_URL = "https://www.imdb.com"

    @staticmethod
    def _request(url):
        flaresolverr_url = _get_config("FlareSolverr").get("url")
        flaresolverr_skipped = _get_db("skip_flaresolverr").retrieve("skipped")

        if not flaresolverr_url or flaresolverr_skipped:
            return None

        try:
            post_data = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000,
            }

            response = requests.post(
                flaresolverr_url,
                json=post_data,
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            if response.status_code == 200:
                json_response = response.json()
                if json_response.get("status") == "ok":
                    return json_response.get("solution", {}).get("response", "")
        except Exception as e:
            debug(f"FlareSolverr request failed for {url}: {e}")

        return None

    @staticmethod
    def get_poster(imdb_id):
        html_content = IMDbFlareSolverr._request(
            f"{IMDbFlareSolverr.WEB_URL}/title/{imdb_id}/"
        )
        if html_content:
            try:
                soup = BeautifulSoup(html_content, "html.parser")
                poster_div = soup.find("div", class_="ipc-poster")
                if poster_div and poster_div.div and poster_div.div.img:
                    poster_set = poster_div.div.img.get("srcset")
                    if poster_set:
                        poster_links = [x for x in poster_set.split(" ") if len(x) > 10]
                        return poster_links[-1]
            except Exception as e:
                debug(f"FlareSolverr poster parsing failed: {e}")
        return None

    @staticmethod
    def get_localized_title(imdb_id, language):
        # FlareSolverr doesn't reliably support headers for localization.
        # Instead, we scrape the release info page which lists AKAs.
        url = f"{IMDbFlareSolverr.WEB_URL}/title/{imdb_id}/releaseinfo"
        html_content = IMDbFlareSolverr._request(url)

        if html_content:
            try:
                soup = BeautifulSoup(html_content, "html.parser")

                # Map language codes to country names commonly used in IMDb AKAs
                country_map = {
                    "de": ["Germany", "Austria", "Switzerland", "West Germany"],
                    "fr": ["France", "Canada", "Belgium"],
                    "es": ["Spain", "Mexico", "Argentina"],
                    "it": ["Italy"],
                    "pt": ["Portugal", "Brazil"],
                    "ru": ["Russia", "Soviet Union"],
                    "ja": ["Japan"],
                    "hi": ["India"],
                }

                target_countries = country_map.get(language, [])

                # Find the AKAs list
                # The structure is a list of items with country names and titles
                items = soup.find_all("li", class_="ipc-metadata-list__item")

                for item in items:
                    label_span = item.find(
                        "span", class_="ipc-metadata-list-item__label"
                    )
                    if not label_span:
                        # Sometimes it's an anchor if it's a link
                        label_span = item.find(
                            "a", class_="ipc-metadata-list-item__label"
                        )

                    if label_span:
                        country = label_span.get_text(strip=True)
                        # Check if this country matches our target language
                        if any(c in country for c in target_countries):
                            # Found a matching country, get the title
                            title_span = item.find(
                                "span",
                                class_="ipc-metadata-list-item__list-content-item",
                            )
                            if title_span:
                                return title_span.get_text(strip=True)

            except Exception as e:
                debug(f"FlareSolverr localized title parsing failed: {e}")

        return None

    @staticmethod
    def search_titles(query, ttype):
        url = f"{IMDbFlareSolverr.WEB_URL}/find/?q={quote(query)}&s=tt&ttype={ttype}&ref_=fn_{ttype}"
        html_content = IMDbFlareSolverr._request(url)

        if html_content:
            try:
                soup = BeautifulSoup(html_content, "html.parser")
                props = soup.find("script", text=re.compile("props"))
                if props:
                    details = loads(props.string)
                    results = details["props"]["pageProps"]["titleResults"]["results"]
                    mapped_results = []
                    for result in results:
                        try:
                            mapped_results.append(
                                {
                                    "id": result["listItem"]["titleId"],
                                    "titleNameText": result["listItem"]["titleText"],
                                    "titleReleaseText": result["listItem"].get(
                                        "releaseYear"
                                    ),
                                }
                            )
                        except KeyError:
                            mapped_results.append(
                                {
                                    "id": result.get("id"),
                                    "titleNameText": result.get("titleNameText"),
                                    "titleReleaseText": result.get("titleReleaseText"),
                                }
                            )
                    return mapped_results

                results = []
                items = soup.find_all("li", class_="ipc-metadata-list-summary-item")
                for item in items:
                    a_tag = item.find("a", class_="ipc-metadata-list-summary-item__t")
                    if a_tag:
                        href = a_tag.get("href", "")
                        id_match = re.search(r"(tt\d+)", href)
                        if id_match:
                            results.append(
                                {
                                    "id": id_match.group(1),
                                    "titleNameText": a_tag.get_text(strip=True),
                                    "titleReleaseText": "",
                                }
                            )
                return results

            except Exception as e:
                debug(f"FlareSolverr search parsing failed: {e}")
        return []


# =============================================================================
# Main Functions (Chain of Responsibility)
# =============================================================================


def _update_cache(imdb_id, key, value, language=None):
    db = _get_db("imdb_metadata")
    try:
        cached_data = db.retrieve(imdb_id)
        if cached_data:
            metadata = loads(cached_data)
        else:
            metadata = {
                "title": None,
                "year": None,
                "poster_link": None,
                "localized": {},
                "ttl": 0,
            }

        if key == "localized" and language:
            if "localized" not in metadata or not isinstance(
                metadata["localized"], dict
            ):
                metadata["localized"] = {}
            metadata["localized"][language] = value
        else:
            metadata[key] = value

        now = datetime.now().timestamp()
        days = 7 if metadata.get("title") and metadata.get("year") else 1
        metadata["ttl"] = now + timedelta(days=days).total_seconds()

        db.update_store(imdb_id, dumps(metadata))
    except Exception as e:
        debug(f"Error updating IMDb metadata cache for {imdb_id}: {e}")


def get_poster_link(shared_state, imdb_id):
    # 0. Check Cache (via get_imdb_metadata)
    imdb_metadata = get_imdb_metadata(imdb_id)
    if imdb_metadata and imdb_metadata.get("poster_link"):
        return imdb_metadata.get("poster_link")

    user_agent = shared_state.values["user_agent"]

    poster = IMDbCDN.get_poster(imdb_id, user_agent)
    if poster:
        _update_cache(imdb_id, "poster_link", poster)
        return poster

    poster = IMDbFlareSolverr.get_poster(imdb_id)
    if poster:
        _update_cache(imdb_id, "poster_link", poster)
        return poster

    debug(f"Could not get poster title for {imdb_id}")
    return None


def get_localized_title(shared_state, imdb_id, language="de"):
    # 0. Check Cache (via get_imdb_metadata)
    imdb_metadata = get_imdb_metadata(imdb_id)
    if imdb_metadata:
        localized = imdb_metadata.get("localized", {}).get(language)
        if localized:
            return localized
        if language == "en" and imdb_metadata.get("title"):
            return imdb_metadata.get("title")

    user_agent = shared_state.values["user_agent"]

    if language == "en":
        title = IMDbCDN.get_title(imdb_id, user_agent)
        if title:
            sanitized_title = TitleCleaner.sanitize(title)
            _update_cache(imdb_id, "title", sanitized_title)
            return sanitized_title

    title = IMDbFlareSolverr.get_localized_title(imdb_id, language)
    if title:
        sanitized_title = TitleCleaner.sanitize(title)
        _update_cache(imdb_id, "localized", sanitized_title, language)
        return sanitized_title

    # Final fallback: Try CDN for English title if localization failed
    title = IMDbCDN.get_title(imdb_id, user_agent)
    if title:
        sanitized_title = TitleCleaner.sanitize(title)
        _update_cache(imdb_id, "title", sanitized_title)
        return sanitized_title

    debug(f"Could not get localized title for {imdb_id} in {language}")
    return None


def get_imdb_metadata(imdb_id):
    db = _get_db("imdb_metadata")
    now = datetime.now().timestamp()
    cached_metadata = None

    # 0. Check Cache
    try:
        cached_data = db.retrieve(imdb_id)
        if cached_data:
            cached_metadata = loads(cached_data)
            if cached_metadata.get("ttl") and cached_metadata["ttl"] > now:
                return cached_metadata
    except Exception as e:
        debug(f"Error retrieving IMDb metadata from DB for {imdb_id}: {e}")
        cached_metadata = None

    imdb_metadata = {
        "title": None,
        "year": None,
        "poster_link": None,
        "localized": {},
        "ttl": 0,
    }

    # 1. Try API
    response_json = IMDbAPI.get_title(imdb_id)

    if response_json:
        imdb_metadata["title"] = TitleCleaner.sanitize(
            response_json.get("primaryTitle", "")
        )
        imdb_metadata["year"] = response_json.get("startYear")

        days = 7 if imdb_metadata.get("title") and imdb_metadata.get("year") else 1
        imdb_metadata["ttl"] = now + timedelta(days=days).total_seconds()

        try:
            imdb_metadata["poster_link"] = response_json.get("primaryImage").get("url")
        except:
            pass

        akas = IMDbAPI.get_akas(imdb_id)
        if akas:
            for aka in akas:
                if aka.get("language"):
                    continue
                if aka.get("country", {}).get("code", "").lower() == "de":
                    imdb_metadata["localized"]["de"] = TitleCleaner.sanitize(
                        aka.get("text")
                    )
                    break

        db.update_store(imdb_id, dumps(imdb_metadata))
        return imdb_metadata

    # API Failed. If we have stale cache, return it.
    if cached_metadata:
        return cached_metadata

    # 2. Fallback: Try CDN for basic info (English title, Year, Poster)
    # We can't get localized titles from CDN, but we can get the rest.
    # We need a user agent, but this function doesn't receive shared_state.
    # We'll skip CDN fallback here to avoid circular deps or complexity,
    # as get_poster_link and get_localized_title handle their own fallbacks.
    # But to populate the DB, we could try. For now, return empty/partial if API fails.

    return imdb_metadata


def get_imdb_id_from_title(shared_state, title, language="de"):
    imdb_id = None

    if re.search(r"S\d{1,3}(E\d{1,3})?", title, re.IGNORECASE):
        ttype_api = "TV_SERIES"
        ttype_web = "tv"
    else:
        ttype_api = "MOVIE"
        ttype_web = "ft"

    title = TitleCleaner.clean(title)

    # 0. Check Search Cache
    db = _get_db("imdb_searches")
    try:
        cached_data = db.retrieve(title)
        if cached_data:
            data = loads(cached_data)
            if data.get("timestamp") and datetime.fromtimestamp(
                data["timestamp"]
            ) > datetime.now() - timedelta(hours=48):
                return data.get("imdb_id")
    except Exception:
        pass

    user_agent = shared_state.values["user_agent"]

    # 1. Try API
    search_results = IMDbAPI.search_titles(title)
    if search_results:
        imdb_id = _match_result(
            shared_state, title, search_results, ttype_api, is_api=True
        )

    # 2. Try CDN (Fallback)
    if not imdb_id:
        search_results = IMDbCDN.search_titles(title, ttype_web, language, user_agent)
        if search_results:
            imdb_id = _match_result(
                shared_state, title, search_results, ttype_api, is_api=False
            )

    # 3. Try FlareSolverr (Last Resort)
    if not imdb_id:
        search_results = IMDbFlareSolverr.search_titles(title, ttype_web)
        if search_results:
            imdb_id = _match_result(
                shared_state, title, search_results, ttype_api, is_api=False
            )

    # Update Cache
    try:
        db.update_store(
            title, dumps({"imdb_id": imdb_id, "timestamp": datetime.now().timestamp()})
        )
    except Exception:
        pass

    if not imdb_id:
        debug(f"No IMDb-ID found for {title}")

    return imdb_id


def _match_result(shared_state, title, results, ttype_api, is_api=False):
    for result in results:
        found_title = (
            result.get("primaryTitle") if is_api else result.get("titleNameText")
        )
        found_id = result.get("id")

        if is_api:
            found_type = result.get("type")
            if ttype_api == "TV_SERIES" and found_type not in [
                "tvSeries",
                "tvMiniSeries",
            ]:
                continue
            if ttype_api == "MOVIE" and found_type not in ["movie", "tvMovie"]:
                continue

        if shared_state.search_string_in_sanitized_title(title, found_title):
            return found_id

    for result in results:
        found_title = (
            result.get("primaryTitle") if is_api else result.get("titleNameText")
        )
        found_id = result.get("id")
        if shared_state.search_string_in_sanitized_title(title, found_title):
            return found_id

    return None


def get_year(imdb_id):
    imdb_metadata = get_imdb_metadata(imdb_id)
    if imdb_metadata:
        return imdb_metadata.get("year")
    return None
