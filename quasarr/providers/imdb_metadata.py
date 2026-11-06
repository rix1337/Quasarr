# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
import time
from datetime import datetime, timedelta
from json import dumps, loads

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import debug, error


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


class IMDbHTML:
    """IMDb release-info HTML scraper used only for localized titles."""

    _WEB_URL = "https://www.imdb.com"
    _HTML_USER_AGENT = (
        "Mozilla/5.0 (compatible; Applebot/0.1; +http://www.apple.com/go/applebot)"
    )
    _LANGUAGE_HEADERS = {
        "de": "de-DE,de;q=0.9,en;q=0.8",
        "en": "en-US,en;q=0.9",
        "fr": "fr-FR,fr;q=0.9,en;q=0.8",
        "es": "es-ES,es;q=0.9,en;q=0.8",
        "it": "it-IT,it;q=0.9,en;q=0.8",
        "pt": "pt-PT,pt;q=0.9,en;q=0.8",
        "ru": "ru-RU,ru;q=0.9,en;q=0.8",
        "ja": "ja-JP,ja;q=0.9,en;q=0.8",
        "hi": "hi-IN,hi;q=0.9,en;q=0.8",
        "zh": "zh-CN,zh;q=0.9,en;q=0.8",
        "ko": "ko-KR,ko;q=0.9,en;q=0.8",
        "ar": "ar,en;q=0.8",
        "tr": "tr-TR,tr;q=0.9,en;q=0.8",
        "pl": "pl-PL,pl;q=0.9,en;q=0.8",
        "nl": "nl-NL,nl;q=0.9,en;q=0.8",
        "sv": "sv-SE,sv;q=0.9,en;q=0.8",
    }

    @staticmethod
    def _request(url, language, deadline=None):
        headers = {
            "Accept-Language": IMDbHTML._LANGUAGE_HEADERS.get(
                language, f"{language},en;q=0.8"
            ),
            "User-Agent": IMDbHTML._HTML_USER_AGENT,
        }
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200 and response.text:
                if IMDbHTML._parse_localized_title(response.text, language):
                    return response.text
                debug("IMDb direct HTML had no proven localized title")
        except Exception as e:
            debug(f"IMDb HTML request failed for {url}: {e}")

        # Browser fallback preserves the old AKA parsing path when direct HTML
        # is unavailable. FlareSolverr cannot reliably set localization headers.
        if deadline is not None and time.time() >= deadline:
            # It allows 60s on its own and the caller stopped waiting, so this
            # is the one stage worth giving up rather than starting.
            debug("Skipped IMDb FlareSolverr fallback: caller out of time")
            return None

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
                timeout=70,
            )
            if response.status_code == 200:
                json_response = response.json()
                if json_response.get("status") == "ok":
                    solution_html = json_response.get("solution", {}).get(
                        "response", ""
                    )
                    if IMDbHTML._parse_localized_title(solution_html, language):
                        return solution_html
                    debug("IMDb FlareSolverr HTML had no proven localized title")
        except Exception as e:
            debug(f"FlareSolverr request failed for {url}: {e}")

        return None

    _COUNTRIES_BY_LANGUAGE = {
        "en": ("United States", "United Kingdom", "Canada", "Australia"),
        "de": ("Germany", "Austria", "Switzerland", "West Germany"),
        "fr": ("France", "Canada", "Belgium"),
        "es": ("Spain", "Mexico", "Argentina"),
        "it": ("Italy",),
        "pt": ("Portugal", "Brazil"),
        "ru": ("Russia", "Soviet Union"),
        "ja": ("Japan",),
        "hi": ("India",),
        "zh": ("China", "Taiwan", "Hong Kong"),
        "ko": ("South Korea",),
        "ar": ("Egypt", "Saudi Arabia", "United Arab Emirates"),
        "tr": ("Turkey",),
        "pl": ("Poland",),
        "nl": ("Netherlands", "Belgium"),
        "sv": ("Sweden",),
    }
    _COUNTRY_CODES_BY_LANGUAGE = {
        "en": ("US", "GB", "CA", "AU"),
        "de": ("DE", "AT", "CH", "XWG"),
        "fr": ("FR", "CA", "BE"),
        "es": ("ES", "MX", "AR"),
        "it": ("IT",),
        "pt": ("PT", "BR"),
        "ru": ("RU", "SUHH"),
        "ja": ("JP",),
        "hi": ("IN",),
        "zh": ("CN", "TW", "HK"),
        "ko": ("KR",),
        "ar": ("EG", "SA", "AE"),
        "tr": ("TR",),
        "pl": ("PL",),
        "nl": ("NL", "BE"),
        "sv": ("SE",),
    }
    _LANGUAGE_CODES_BY_NAME = {
        "english": "en",
        "german": "de",
        "french": "fr",
        "spanish": "es",
        "italian": "it",
        "portuguese": "pt",
        "russian": "ru",
        "japanese": "ja",
        "hindi": "hi",
        "chinese": "zh",
        "mandarin": "zh",
        "korean": "ko",
        "arabic": "ar",
        "turkish": "tr",
        "polish": "pl",
        "dutch": "nl",
        "swedish": "sv",
    }

    @staticmethod
    def _next_data(soup):
        node = soup.find("script", id="__NEXT_DATA__")
        if node is None or not node.string:
            return None
        try:
            return loads(node.string)
        except Exception:
            return None

    @staticmethod
    def _localized_titles_from_next_data(next_data, language):
        if not isinstance(next_data, dict):
            return None, None

        props = next_data.get("props")
        page_props = props.get("pageProps") if isinstance(props, dict) else None
        if not isinstance(page_props, dict):
            return None, None
        content_data = page_props.get("contentData")
        if not isinstance(content_data, dict):
            return None, None
        data = content_data.get("data")
        title_data = data.get("title") if isinstance(data, dict) else {}
        if not isinstance(title_data, dict):
            title_data = {}

        country_codes = IMDbHTML._COUNTRY_CODES_BY_LANGUAGE.get(language, ())
        country_matches = []
        akas = title_data.get("akas")
        edges = akas.get("edges", []) if isinstance(akas, dict) else []
        for edge in edges or []:
            node = edge.get("node", {}) if isinstance(edge, dict) else {}
            if not isinstance(node, dict):
                continue
            country = node.get("country")
            country_code = country.get("id") if isinstance(country, dict) else None
            aka_language = node.get("language")
            aka_language = (
                aka_language.get("id", "").lower()
                if isinstance(aka_language, dict)
                else ""
            )
            displayable_property = node.get("displayableProperty")
            value = (
                displayable_property.get("value")
                if isinstance(displayable_property, dict)
                else None
            )
            title = value.get("plainText") if isinstance(value, dict) else None
            if not title:
                continue
            if aka_language == language:
                return title, None
            if country_code in country_codes and not aka_language:
                country_matches.append(title)

        if country_matches:
            return country_matches[0], None

        request_context = page_props.get("requestContext")
        sidecar = (
            request_context.get("sidecar")
            if isinstance(request_context, dict)
            else None
        )
        localization = (
            sidecar.get("localizationResponse") if isinstance(sidecar, dict) else None
        )
        if not isinstance(localization, dict):
            return None, None
        user_language = localization.get("userLanguage", "").split("-", 1)[0].lower()
        locale_is_proven = (
            user_language == language
            and localization.get("isFullLocalizationEnabled") is True
            and localization.get("isOriginalTitlePreferenceSet") is False
        )
        if not locale_is_proven:
            return None, None

        entity_metadata = content_data.get("entityMetadata")
        title_text = (
            entity_metadata.get("titleText")
            if isinstance(entity_metadata, dict)
            else None
        ) or title_data.get("titleText")
        localized_title = (
            title_text.get("text") if isinstance(title_text, dict) else None
        )
        return None, localized_title

    @staticmethod
    def _row_has_conflicting_language(values, language):
        for value in values:
            qualifier = value.strip().strip("()").lower()
            for name, code in IMDbHTML._LANGUAGE_CODES_BY_NAME.items():
                if qualifier == name or qualifier.startswith(f"{name} "):
                    return code != language
        return False

    @staticmethod
    def _parse_localized_title(html_content, language):
        """Parse a localized title from IMDb's current AKA HTML section."""
        if not html_content:
            return None

        language = language.lower()
        soup = BeautifulSoup(html_content, "html.parser")
        embedded_aka, localized_page_title = IMDbHTML._localized_titles_from_next_data(
            IMDbHTML._next_data(soup), language
        )
        if embedded_aka:
            return embedded_aka

        target_countries = IMDbHTML._COUNTRIES_BY_LANGUAGE.get(language, ())
        if not target_countries:
            return localized_page_title

        heading = soup.find(id="akas")
        akas_section = soup.find(attrs={"data-testid": "sub-section-akas"})
        if akas_section is None and heading is not None:
            akas_section = heading.find_parent("section")
        if akas_section is None:
            return localized_page_title

        # Current IMDb markup uses generic nested elements under the #akas
        # section. Country and title are adjacent text values in each row.
        for country_node in akas_section.find_all(string=True):
            country = country_node.strip()
            if not any(
                country == target or country.startswith(f"{target} (")
                for target in target_countries
            ):
                continue

            element = country_node.parent
            row = element.find_parent(["li", "tr"])
            if row is None:
                row = element.parent
            values = [value.strip() for value in row.stripped_strings if value.strip()]
            try:
                country_index = values.index(country)
            except ValueError:
                continue
            if country_index + 1 < len(
                values
            ) and not IMDbHTML._row_has_conflicting_language(
                values[country_index + 2 :], language
            ):
                return values[country_index + 1]

        # Preserve compatibility with the previous metadata-list markup, but
        # keep lookup scoped to the AKA section so release-date countries do
        # not get mistaken for localized titles.
        for item in akas_section.select("li.ipc-metadata-list__item"):
            label = item.select_one(
                ".ipc-metadata-list-item__label, "
                ".ipc-metadata-list-item__list-content-item"
            )
            if not label:
                continue
            country = label.get_text(" ", strip=True)
            if not any(target in country for target in target_countries):
                continue
            values = [value.strip() for value in item.stripped_strings if value.strip()]
            if len(values) > 1 and not IMDbHTML._row_has_conflicting_language(
                values[2:], language
            ):
                return values[1]

        return localized_page_title

    @staticmethod
    def get_localized_title(imdb_id, language, deadline=None):
        # The locale-specific HTML metadata is primary. The parser retains an
        # AKA-section fallback for older or browser-rendered responses.
        language = language.lower()
        if language == "en":
            # IMDb serves English at the unprefixed default path and 404s on /en/.
            url = f"{IMDbHTML._WEB_URL}/title/{imdb_id}/releaseinfo/"
        else:
            url = f"{IMDbHTML._WEB_URL}/{language}/title/{imdb_id}/releaseinfo/"
        html_content = IMDbHTML._request(url, language, deadline=deadline)

        if html_content:
            try:
                title = IMDbHTML._parse_localized_title(html_content, language)
                if title:
                    return title
            except Exception as e:
                debug(f"IMDb HTML localized title parsing failed for {imdb_id}: {e}")

        return None


# =============================================================================
# Main Functions (Chain of Responsibility)
# =============================================================================


def _empty_metadata():
    return {
        "title": None,
        "year": None,
        "poster_link": None,
        "localized": {},
        "ttl": 0,
    }


def _normalize_localized_title(title, language):
    """Return one source-facing representation for a localized title."""
    if not title:
        return None
    title = TitleCleaner.sanitize(title)
    if language.lower() == "de":
        # Apply the project's canonical German source-query spelling once so
        # every source receives the same value without source-specific retries.
        from quasarr.providers.utils import replace_umlauts

        title = replace_umlauts(title)
    return title


def _get_cached_metadata(imdb_id):
    try:
        cached_data = _get_db("imdb_metadata").retrieve(imdb_id)
        if not cached_data:
            return None
        metadata = loads(cached_data)
        return metadata
    except Exception as e:
        debug(f"Error retrieving IMDb metadata from DB for {imdb_id}: {e}")
        return None


def _poster_from_arr_record(record):
    if record.get("remotePoster"):
        return record["remotePoster"]
    for image in record.get("images") or []:
        if image.get("coverType") != "poster":
            continue
        poster = image.get("remoteUrl") or image.get("url")
        if poster and poster.startswith(("http://", "https://")):
            return poster
    return None


def _localized_titles_from_arr_record(record):
    """Use only alternate titles carrying an explicit ISO language code."""
    localized = {}
    for alternate in record.get("alternateTitles") or []:
        if not isinstance(alternate, dict):
            continue
        language = (
            alternate.get("languageCode")
            or alternate.get("iso6391")
            or alternate.get("language")
        )
        if isinstance(language, dict):
            language = language.get("code") or language.get("iso6391")
        if not isinstance(language, str) or not re.fullmatch(r"[a-zA-Z]{2}", language):
            continue
        title = TitleCleaner.sanitize(alternate.get("title"))
        if title:
            localized.setdefault(language.lower(), title)

    # Arr alternate titles carry no language codes, but the original-language
    # title is language-proven even when the instance localizes its display title.
    original_language = record.get("originalLanguage")
    language_name = (
        original_language.get("name") if isinstance(original_language, dict) else None
    )
    code = (
        IMDbHTML._LANGUAGE_CODES_BY_NAME.get(language_name.lower())
        if isinstance(language_name, str)
        else None
    )
    if code:
        original_title = TitleCleaner.sanitize(
            record.get("originalTitle") or record.get("title")
        )
        if original_title:
            localized.setdefault(code, original_title)

    return localized


def _metadata_from_arr_record(record):
    metadata = _empty_metadata()
    metadata["title"] = TitleCleaner.sanitize(
        record.get("title") or record.get("originalTitle")
    )
    metadata["year"] = record.get("year")
    metadata["poster_link"] = _poster_from_arr_record(record)
    metadata["localized"] = _localized_titles_from_arr_record(record)
    complete = metadata["title"] and metadata["year"] and metadata["poster_link"]
    metadata["ttl"] = (
        datetime.now().timestamp()
        + timedelta(days=7 if complete else 1).total_seconds()
    )
    return metadata


def _lookup_arr_record(shared_state, imdb_id, search_category=None):
    from quasarr.constants import SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS
    from quasarr.providers.radarr_api import get_client as get_radarr_client
    from quasarr.providers.sonarr_api import get_client as get_sonarr_client
    from quasarr.providers.utils import get_base_search_category_id

    base_search_category = get_base_search_category_id(search_category)
    if base_search_category == SEARCH_CAT_MOVIES:
        clients = ((get_radarr_client(shared_state), "movie_lookup_imdb"),)
    elif base_search_category == SEARCH_CAT_SHOWS:
        clients = ((get_sonarr_client(shared_state), "series_lookup_imdb"),)
    else:
        clients = (
            (get_radarr_client(shared_state), "movie_lookup_imdb"),
            (get_sonarr_client(shared_state), "series_lookup_imdb"),
        )

    for client, method_name in clients:
        if client is None:
            continue
        record = getattr(client, method_name)(imdb_id)
        if record:
            return record
    return None


def _refresh_imdb_metadata(
    shared_state, imdb_id, search_category, cached_metadata=None
):
    record = _lookup_arr_record(shared_state, imdb_id, search_category)
    if not record:
        return cached_metadata or _empty_metadata(), {}

    metadata = _metadata_from_arr_record(record)
    arr_localized = dict(metadata["localized"])
    if cached_metadata:
        metadata["localized"] = {
            **cached_metadata.get("localized", {}),
            **metadata["localized"],
        }
    _get_db("imdb_metadata").update_store(imdb_id, dumps(metadata))
    return metadata, arr_localized


def _update_cache(imdb_id, key, value, language=None):
    db = _get_db("imdb_metadata")
    try:
        cached_data = db.retrieve(imdb_id)
        if cached_data:
            metadata = loads(cached_data)
        else:
            metadata = _empty_metadata()

        if key == "localized" and language:
            if "localized" not in metadata or not isinstance(
                metadata["localized"], dict
            ):
                metadata["localized"] = {}
            metadata["localized"][language] = value
        else:
            metadata[key] = value

        now = datetime.now().timestamp()
        metadata["ttl"] = now + timedelta(hours=24).total_seconds()

        db.update_store(imdb_id, dumps(metadata))
    except Exception as e:
        debug(f"Error updating IMDb metadata cache for {imdb_id}: {e}")


def get_poster_link(shared_state, imdb_id, search_category=None):
    imdb_metadata = get_imdb_metadata(shared_state, imdb_id, search_category)
    if imdb_metadata and imdb_metadata.get("poster_link"):
        return imdb_metadata.get("poster_link")

    debug(f"Could not get poster for {imdb_id} from Radarr or Sonarr")
    return None


def get_localized_title(
    shared_state, imdb_id, language="de", search_category=None, deadline=None
):
    """Resolve a localized title, optionally within a caller's wall-clock budget.

    ``deadline`` is an absolute time. Cache hits always answer; the Arr refresh
    and the IMDb HTML/FlareSolverr fallbacks are skipped once it has passed,
    because those cost real requests (the browser fallback alone allows 70s) and
    would otherwise run long after the caller stopped waiting for them.
    """

    def out_of_time():
        # Re-read on every gate: the Arr refresh between them costs a request of
        # its own, so a budget that was intact on entry can be gone by the time
        # the far more expensive IMDb fallbacks would start.
        return deadline is not None and time.time() >= deadline

    imdb_metadata = _get_cached_metadata(imdb_id)
    cache_is_fresh = bool(
        imdb_metadata and imdb_metadata.get("ttl", 0) > datetime.now().timestamp()
    )
    if cache_is_fresh:
        localized = imdb_metadata.get("localized", {}).get(language)
        if localized:
            return _normalize_localized_title(localized, language)
    elif not out_of_time():
        imdb_metadata, arr_localized = _refresh_imdb_metadata(
            shared_state, imdb_id, search_category, imdb_metadata
        )
        localized = arr_localized.get(language)
        if localized:
            return _normalize_localized_title(localized, language)

    if out_of_time():
        debug(f"Skipped localized-title lookup for {imdb_id}: caller out of time")
        return None

    title = IMDbHTML.get_localized_title(imdb_id, language, deadline=deadline)
    if title:
        sanitized_title = TitleCleaner.sanitize(title)
        _update_cache(imdb_id, "localized", sanitized_title, language)
        return _normalize_localized_title(sanitized_title, language)

    error(f"Could not get localized title for {imdb_id} in {language}")
    return None


def get_imdb_metadata(shared_state, imdb_id, search_category=None):
    cached_metadata = _get_cached_metadata(imdb_id)
    if cached_metadata and cached_metadata.get("ttl", 0) > datetime.now().timestamp():
        return cached_metadata

    metadata, _arr_localized = _refresh_imdb_metadata(
        shared_state, imdb_id, search_category, cached_metadata
    )
    return metadata


def get_imdb_id_from_title(shared_state, title, language="de"):
    from quasarr.providers.radarr_api import get_client as get_radarr_client
    from quasarr.providers.sonarr_api import get_client as get_sonarr_client

    is_series = bool(re.search(r"S\d{1,3}(E\d{1,3})?", title, re.IGNORECASE))
    title = TitleCleaner.clean(title)
    lookup_term = title.replace("+", " ")

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

    if is_series:
        client = get_sonarr_client(shared_state)
        search_results = client.series_lookup(lookup_term) if client else []
    else:
        client = get_radarr_client(shared_state)
        search_results = client.movie_lookup(lookup_term) if client else []
    imdb_id = _match_arr_result(lookup_term, search_results)

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


def _match_arr_result(title, results):
    from quasarr.providers.utils import search_string_in_sanitized_title

    match_title = re.sub(r"\s+(?:19|20)\d{2}$", "", title).strip()
    for result in results:
        imdb_id = result.get("imdbId")
        if not imdb_id:
            continue
        candidate_titles = [result.get("title"), result.get("originalTitle")]
        for alternate in result.get("alternateTitles") or []:
            candidate_titles.append(
                alternate.get("title") if isinstance(alternate, dict) else alternate
            )
        if any(
            candidate and search_string_in_sanitized_title(match_title, candidate)
            for candidate in candidate_titles
        ):
            return imdb_id

    return None


def get_year(imdb_id):
    imdb_metadata = _get_cached_metadata(imdb_id)
    if imdb_metadata:
        return imdb_metadata.get("year")
    return None
