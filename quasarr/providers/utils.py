# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import json
import os
import re
import socket
import sys
import traceback
import unicodedata
from base64 import urlsafe_b64decode, urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from io import BytesIO
from urllib.parse import urlencode, urlparse

import requests
from PIL import Image

from quasarr.constants import (
    CLIENT_DOWNLOAD_CATEGORY_FALLBACK_MAP,
    DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    MONTHS_MAP,
    MOVIE_REGEX,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MOVIES_HD,
    SEARCH_CAT_MOVIES_UHD,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_MUSIC_FLAC,
    SEARCH_CAT_MUSIC_MP3,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_HD,
    SEARCH_CAT_SHOWS_UHD,
    SEARCH_CAT_XXX,
    SEARCH_CATEGORIES,
    SEARCH_CATEGORY_CACHE_FAMILIES,
    SEASON_EP_REGEX,
    SESSION_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import radarr_api, sonarr_api
from quasarr.providers.log import crit, debug, error, trace, warn
from quasarr.search.sources.helpers import (
    get_login_required_hostnames,
    get_radarr_required_hostnames,
    get_sonarr_required_hostnames,
)
from quasarr.storage.categories import download_category_exists, search_category_exists
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase


class Unbuffered(object):
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def writelines(self, datas):
        self.stream.writelines(datas)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def is_valid_url(url):
    """Validate if a URL is properly formatted."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def extract_allowed_keys(config, section):
    """
    Extracts allowed keys from the specified section in the configuration.

    :param config: The configuration dictionary.
    :param section: The section from which to extract keys.
    :return: A list of allowed keys.
    """
    if section not in config:
        raise ValueError(f"Section '{section}' not found in configuration.")
    return [key for key, *_ in config[section]]


def extract_kv_pairs(input_text, allowed_keys):
    """
    Extracts key-value pairs from the given text where keys match allowed_keys.

    :param input_text: The input text containing key-value pairs.
    :param allowed_keys: A list of allowed two-letter shorthand keys.
    :return: A dictionary of extracted key-value pairs.
    """
    kv_pattern = re.compile(rf"^({'|'.join(map(re.escape, allowed_keys))})\s*=\s*(.*)$")
    kv_pairs = {}

    for line in input_text.splitlines():
        match = kv_pattern.match(line.strip())
        if match:
            key, value = match.groups()
            kv_pairs[key] = value
        elif "[Hostnames]" in line:
            pass
        else:
            trace(
                f"Skipping line because it does not contain any supported hostname: {line}"
            )

    return kv_pairs


def check_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 0))
        ip = s.getsockname()[0]
    except:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def check_flaresolverr(shared_state, flaresolverr_url):
    # Ensure it ends with /v<digit+>
    if not re.search(r"/v\d+$", flaresolverr_url):
        error(f"FlareSolverr URL does not end with /v#: {flaresolverr_url}")
        return False

    # Try sending a simple test request
    headers = {"Content-Type": "application/json"}
    data = {"cmd": "request.get", "url": "http://www.google.com/", "maxTimeout": 10000}

    try:
        response = requests.post(
            flaresolverr_url,
            headers=headers,
            json=data,
            timeout=SESSION_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        json_data = response.json()

        # Check if the structure looks like a valid FlareSolverr response
        if "status" in json_data and json_data["status"] == "ok":
            solution = json_data["solution"]
            solution_ua = solution.get("userAgent", None)
            if solution_ua:
                shared_state.update("user_agent", solution_ua)
            try:
                flaresolverr_version = json_data.get("version")
            except Exception as e:
                error(f"Could not grab Flaresolverr version: {str(e)}")
                return False
            return flaresolverr_version
        else:
            error(f"Unexpected FlareSolverr response: {json_data}")
            return False

    except Exception as e:
        error(f"Failed to connect to FlareSolverr: {e}")
        return False


def validate_address(address, name):
    if not address.startswith("http"):
        crit(f"Error: {name} '{address}' is invalid. It must start with 'http'.")
        sys.exit(1)

    colon_count = address.count(":")
    if colon_count < 1 or colon_count > 2:
        crit(
            f"Error: {name} '{address}' is invalid. It must contain 1 or 2 colons, but it has {colon_count}."
        )
        sys.exit(1)


def is_flaresolverr_available(shared_state):
    """
    Check if FlareSolverr is configured and available.

    Returns:
        bool: True if FlareSolverr URL is set and not skipped, False otherwise
    """
    # Check if FlareSolverr was skipped
    if shared_state.values["database"]("skip_flaresolverr").retrieve("skipped"):
        return False

    # Check if FlareSolverr URL is configured
    flaresolverr_url = shared_state.values["config"]("FlareSolverr").get("url")
    if not flaresolverr_url:
        return False

    return True


def is_site_usable(shared_state, shorthand):
    """
    Check if a site is fully configured and usable.

    For sites that don't require login, just checks if hostname is set.
    For login-required sites (al, dd, dl, nx), also checks that login wasn't skipped
    and that credentials exist. For Radarr/Sonarr-required sites, also checks that
    the corresponding client is cached in shared_state.

    Args:
        shared_state: Shared state object
        shorthand: Site shorthand (e.g., 'al', 'dd', etc.)

    Returns:
        bool: True if site is usable, False otherwise
    """
    shorthand = shorthand.lower()

    # Check if hostname is set
    hostname = shared_state.values["config"]("Hostnames").get(shorthand)
    if not hostname:
        return False

    # Keep dual-category sources usable with either configured Arr client.
    # Import lazily because setup modules also consume provider services.
    from quasarr.storage.setup.arr import missing_arr_client_requirement

    if missing_arr_client_requirement(
        shorthand,
        set(get_radarr_required_hostnames()),
        set(get_sonarr_required_hostnames()),
        bool(radarr_api.get_client(shared_state)),
        bool(sonarr_api.get_client(shared_state)),
    ):
        return False

    if shorthand not in get_login_required_hostnames():
        return True  # No login needed, hostname is enough

    # Check if login was skipped
    if shared_state.values["database"]("skip_login").retrieve(shorthand):
        return False  # Hostname set but login was skipped

    # Check for credentials
    section = "JUNKIES" if shorthand in ["dj", "sj"] else shorthand.upper()
    config = shared_state.values["config"](section)
    user = config.get("user")
    password = config.get("password")

    return bool(user and password)


def generate_download_link(
    shared_state, title, url, size_mb, password, imdb_id, source_key
):
    """
    Generate a download link with a base64 encoded payload.
    The payload format is: title|url|size_mb|password|imdb_id|source_key

    Args:
        shared_state: Shared state object
        title: Release title
        url: Source URL
        size_mb: Size in MB (int or float)
        password: Password for the release (or empty string)
        imdb_id: IMDb ID (or None/empty string)
        source_key: Source shorthand (e.g., 'al', 'dd')

    Returns:
        str: Full download URL
    """
    # Ensure all fields are strings and handle None
    title = str(title) if title else ""
    url = str(url) if url else ""
    size_mb = str(size_mb) if size_mb is not None else "0"
    password = str(password) if password else ""
    imdb_id = str(imdb_id) if imdb_id else ""
    source_key = str(source_key) if source_key else ""

    raw_payload = f"{title}|{url}|{size_mb}|{password}|{imdb_id}|{source_key}"
    encoded_payload = urlsafe_b64encode(raw_payload.encode("utf-8")).decode("utf-8")

    query = urlencode(
        {
            "payload": encoded_payload,
            "apikey": Config("API").get("key") or "",
        }
    )
    return f"{shared_state.values['internal_address']}/download/?{query}"


# =============================================================================
# LINK STATUS CHECKING
# =============================================================================


def generate_status_url(href, crypter_type):
    """
    Generate a status URL for crypters that support it.
    Returns None if status URL cannot be generated.
    """
    if crypter_type == "hide":
        # hide.cx links: https://hide.cx/folder/{UUID} or /container/{UUID} → https://hide.cx/state/{UUID}
        match = re.search(
            r"hide\.cx/(?:folder/|container/)?([a-f0-9-]{36})", href, re.IGNORECASE
        )
        if match:
            uuid = match.group(1)
            return f"https://hide.cx/state/{uuid}"

    elif crypter_type == "tolink":
        # tolink links: https://tolink.to/f/{ID} → https://tolink.to/f/{ID}/s/status.png
        match = re.search(r"tolink\.to/f/([a-zA-Z0-9]+)", href, re.IGNORECASE)
        if match:
            link_id = match.group(1)
            return f"https://tolink.to/f/{link_id}/s/status.png"

    return None


def detect_crypter_type(url):
    """Detect crypter type from URL for status checking."""
    url_lower = url.lower()
    if "hide." in url_lower:
        return "hide"
    elif "tolink." in url_lower:
        return "tolink"
    elif "filecrypt." in url_lower:
        return "filecrypt"
    elif "keeplinks." in url_lower:
        return "keeplinks"
    return None


def image_has_green(image_data):
    """
    Analyze image data to check if it contains green pixels.
    Returns True if any significant green is detected (indicating online status).
    """
    try:
        img = Image.open(BytesIO(image_data))
        # Convert palette images with transparency to RGBA first to avoid warning
        if img.mode == "P" and "transparency" in img.info:
            img = img.convert("RGBA")
        img = img.convert("RGB")

        pixels = list(img.getdata())

        for r, g, b in pixels:
            # Check if pixel is greenish: green channel is dominant
            # and has a reasonable absolute value
            if g > 100 and g > r * 1.3 and g > b * 1.3:
                return True

        return False
    except Exception:
        # If we can't analyze, assume online to not skip valid links
        return True


def fetch_status_image(status_url, shared_state=None):
    """
    Fetch a status image and return (status_url, image_data).
    Returns (status_url, None) on failure.
    """
    try:
        headers = {}
        if shared_state:
            user_agent = shared_state.values.get("user_agent")
            if user_agent:
                headers["User-Agent"] = user_agent
        response = requests.get(
            status_url,
            headers=headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            return (status_url, response.content)
    except Exception:
        pass
    return (status_url, None)


def check_links_online_status(links_with_status, shared_state=None):
    """
    Check online status for links that have status URLs.
    Returns list of links that are online (or have no status URL to check).

    links_with_status: list of [href, identifier, status_url] where status_url can be None
    shared_state: optional shared state for user agent
    """
    links_to_check = [(i, link) for i, link in enumerate(links_with_status) if link[2]]

    if not links_to_check:
        # No status URLs to check, return all links as potentially online
        return [[link[0], link[1]] for link in links_with_status]

    # Batch fetch status images
    status_results = {}  # status_url -> has_green
    status_urls = list(set(link[2] for _, link in links_to_check))

    batch_size = 10
    for i in range(0, len(status_urls), batch_size):
        batch = status_urls[i : i + batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = [
                executor.submit(fetch_status_image, url, shared_state) for url in batch
            ]
            for future in as_completed(futures):
                try:
                    status_url, image_data = future.result()
                    if image_data:
                        status_results[status_url] = image_has_green(image_data)
                    else:
                        # Could not fetch, assume online
                        status_results[status_url] = True
                except Exception:
                    pass

    # Filter to online links
    online_links = []

    for link in links_with_status:
        href, identifier, status_url = link
        if not status_url:
            # No status URL, include link
            online_links.append([href, identifier])
        elif status_url in status_results:
            if status_results[status_url]:
                online_links.append([href, identifier])
        else:
            # Status check failed, include link
            online_links.append([href, identifier])

    return online_links


def filter_offline_links(links, shared_state=None, log_func=None):
    """
    Filter out offline links from a list of [url, identifier] pairs.
    Only checks links where status can be verified (hide.cx, tolink).
    Returns filtered list of [url, identifier] pairs.
    """
    if not links:
        return links

    # Build list with status URLs
    links_with_status = []
    for link in links:
        url = link[0]
        identifier = link[1] if len(link) > 1 else "unknown"
        crypter_type = detect_crypter_type(url)
        status_url = generate_status_url(url, crypter_type) if crypter_type else None
        links_with_status.append([url, identifier, status_url])

    # Check if any links can be verified
    verifiable_count = sum(1 for l in links_with_status if l[2])
    if verifiable_count == 0:
        # Nothing to verify, return original links
        return links

    if log_func:
        log_func(f"Checking online status for {verifiable_count} verifiable link(s)...")

    # Check status and filter
    online_links = check_links_online_status(links_with_status, shared_state)

    if log_func and len(online_links) < len(links):
        offline_count = len(links) - len(online_links)
        log_func(f"Filtered out {offline_count} offline link(s)")

    return online_links


def parse_payload(payload_str):
    """
    Parse the base64-encoded payload string into its components.

    Format: title|url|size_mb|password|imdb_id|source_key

    Returns:
        dict with keys: title, url, size_mb, password, imdb_id, source_key
    """
    decoded = urlsafe_b64decode(payload_str.encode()).decode()
    parts = decoded.split("|")

    if len(parts) == 6:
        title, url, size_mb, password, imdb_id, source_key = parts
    else:
        raise ValueError(f"expected 6 fields, got {len(parts)}")

    return {
        "title": normalize_download_title(title),
        "url": url,
        "size_mb": size_mb,
        "password": password if password else None,
        "imdb_id": imdb_id if imdb_id else None,
        "source_key": source_key if source_key else None,
    }


def normalize_download_title(title):
    """
    Normalize download titles at handoff time.
    Removes trailing marker suffixes like "*mirror*" and trims whitespace.
    """
    normalized = str(title or "").rstrip()
    normalized = re.sub(r"\s*\*mirror\*\s*$", "", normalized, flags=re.IGNORECASE)
    return normalized.rstrip()


def determine_category(request_from, category=None):
    """
    Determine the category based on the provided category or the client type.
    If category is not provided or invalid, falls back to default mapping based on request_from.
    """
    if category and download_category_exists(category):
        return category

    client_type = extract_client_type(request_from)
    return CLIENT_DOWNLOAD_CATEGORY_FALLBACK_MAP.get(client_type, "tv")


def get_base_search_category_id(cat_id):
    """
    Resolves a category ID (default, subcategory, or custom) to its base type ID.
    Falls back to stored base_type metadata when ID math alone is ambiguous.
    """
    try:
        cat_id = int(cat_id)
    except (ValueError, TypeError):
        return None

    # Custom categories are in the 100000+ range
    if cat_id >= 100000:
        # e.g. 102010 -> 2010 -> 2000
        # e.g. 103000 -> 3000 -> 3000
        base = (cat_id - 100000) // 1000 * 1000
        if base in [
            SEARCH_CAT_MOVIES,
            SEARCH_CAT_MUSIC,
            SEARCH_CAT_SHOWS,
            SEARCH_CAT_BOOKS,
        ]:
            return base

    # Standard categories and their subcategories
    elif 2000 <= cat_id < 3000:
        return SEARCH_CAT_MOVIES
    elif 3000 <= cat_id < 4000:
        return SEARCH_CAT_MUSIC
    elif 5000 <= cat_id < 6000:
        return SEARCH_CAT_SHOWS
    elif 6000 <= cat_id < 7000:
        return SEARCH_CAT_XXX
    elif 7000 <= cat_id < 8000:
        return SEARCH_CAT_BOOKS

    # Fallback: custom category IDs may not always be reversible from ID math.
    db = DataBase("categories_search")
    data_str = db.retrieve(str(cat_id))
    if not data_str:
        return None

    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        return None

    base_type = data.get("base_type")
    base_type_name_map = {
        "movies": SEARCH_CAT_MOVIES,
        "music": SEARCH_CAT_MUSIC,
        "tv": SEARCH_CAT_SHOWS,
        "books": SEARCH_CAT_BOOKS,
    }

    if isinstance(base_type, str):
        if base_type in base_type_name_map:
            return base_type_name_map[base_type]
        try:
            base_type = int(base_type)
        except ValueError:
            return None

    if isinstance(base_type, int) and base_type in SEARCH_CATEGORIES:
        return base_type

    return None


def get_search_behavior_category(cat_id):
    """
    Resolve the effective category behavior for search execution/filtering.

    - Default categories return themselves.
    - Custom categories (100000+) return their stored base_type when available.
      This allows custom categories derived from subcategories (e.g. 2040/5070)
      to behave exactly like those categories except for whitelist ownership.
    """
    try:
        cat_id = int(cat_id)
    except (ValueError, TypeError):
        return None

    if cat_id < 100000:
        return cat_id

    db = DataBase("categories_search")
    data_str = db.retrieve(str(cat_id))
    if data_str:
        try:
            data = json.loads(data_str)
            base_type = data.get("base_type")
            if isinstance(base_type, str):
                try:
                    base_type = int(base_type)
                except ValueError:
                    base_type = None
            if isinstance(base_type, int) and base_type in SEARCH_CATEGORIES:
                return base_type
        except json.JSONDecodeError:
            pass

    # Fallback for custom IDs derived directly from category IDs.
    direct_base_candidate = cat_id - 100000
    if direct_base_candidate in SEARCH_CATEGORIES:
        return direct_base_candidate

    # Final fallback to canonical base type.
    return get_base_search_category_id(cat_id)


SEARCH_SUBCATEGORY_CAPABILITY_BASE = {
    SEARCH_CAT_MOVIES_HD: SEARCH_CAT_MOVIES,
    SEARCH_CAT_MOVIES_UHD: SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS_HD: SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_UHD: SEARCH_CAT_SHOWS,
    SEARCH_CAT_MUSIC_MP3: SEARCH_CAT_MUSIC,
    SEARCH_CAT_MUSIC_FLAC: SEARCH_CAT_MUSIC,
}

SEARCH_CACHE_OWNER_BY_CATEGORY = {
    category_id: owner_id
    for owner_id, category_ids in SEARCH_CATEGORY_CACHE_FAMILIES.items()
    for category_id in category_ids
}


_HD_RESOLUTION_PATTERN = re.compile(r"\b(?:720p|720i|1080p|1080i|fullhd|fhd)\b", re.I)
_STRONG_4K_PATTERN = re.compile(r"\b(?:2160p|2160i|4k)\b", re.I)
_UHD_PATTERN = re.compile(r"\buhd\b", re.I)


_SEARCH_SUBCATEGORY_TITLE_FILTERS = {
    SEARCH_CAT_MOVIES_HD: _HD_RESOLUTION_PATTERN,
    SEARCH_CAT_SHOWS_HD: _HD_RESOLUTION_PATTERN,
    SEARCH_CAT_MUSIC_MP3: re.compile(r"\bmp3\b", re.I),
    SEARCH_CAT_MUSIC_FLAC: re.compile(r"\b(?:flac|lossless)\b", re.I),
}


def get_search_capability_category(cat_id):
    """
    Resolve the category used for source capability checks.

    - Base categories keep their own ID.
    - Quality/format subcategories map to their base category capability.
    - Custom categories map to their resolved base category.
    """
    behavior_category = get_search_behavior_category(cat_id)
    if behavior_category is None:
        return None
    return SEARCH_SUBCATEGORY_CAPABILITY_BASE.get(behavior_category, behavior_category)


def get_search_cache_owner_category(cat_id):
    """
    Resolve which category should own shared search result cache entries.

    - Cache families are explicitly defined in constants for maintainability.
    - Custom categories (100000+) keep independent cache ownership.
    - Categories outside the mapping are standalone owners.
    """
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        return cat_id

    if cat_id >= 100000:
        return cat_id

    return SEARCH_CACHE_OWNER_BY_CATEGORY.get(cat_id, cat_id)


def get_search_cache_family_groups(categories):
    """
    Build explicit cache-family execution groups.

    Returns an ordered list of tuples:
    - (owner_category_id, [ordered_category_ids])

    Semantics:
    - Categories in the same group share one cache owner key.
    - The first (lowest) category in a group is expected to populate cache.
    - Remaining categories in the group are expected to run after it and reuse cache.
    """
    normalized = sorted(
        {
            int(cat_id)
            for cat_id in categories
            if isinstance(cat_id, int) or str(cat_id).isdigit()
        }
    )
    grouped = {}
    for category_id in normalized:
        owner_id = get_search_cache_owner_category(category_id)
        grouped.setdefault(owner_id, []).append(category_id)

    return [(owner_id, sorted(grouped[owner_id])) for owner_id in sorted(grouped)]


def format_search_cache_family_groups(groups):
    """Format cache-family groups for logs."""
    return ", ".join(
        f"{owner_id}:[{','.join(str(cat) for cat in categories)}]"
        for owner_id, categories in groups
    )


def has_source_capability_for_category(cat_id, supported_categories):
    """Check whether at least one source capability can serve the given category."""
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        return False

    # Always expose custom categories.
    if cat_id >= 100000:
        return True

    capability_category = get_search_capability_category(cat_id)
    if capability_category is None:
        return False
    return capability_category in supported_categories


def _normalize_release_title_for_category_match(title):
    title = html.unescape(str(title or ""))
    title = re.sub(r"[._-]+", " ", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def release_matches_search_category(search_category, release_title):
    """
    Return True when a release title matches the requested subcategory rules.
    Categories without title filters are accepted as-is.
    """
    behavior_category = get_search_behavior_category(search_category)
    if behavior_category is None:
        return True

    normalized_title = _normalize_release_title_for_category_match(release_title)

    # UHD categories: require explicit UHD signal (2160/4k), or UHD without lower-res tags.
    # This prevents false positives like "1080p ... UHD ...".
    if behavior_category in (SEARCH_CAT_MOVIES_UHD, SEARCH_CAT_SHOWS_UHD):
        if _STRONG_4K_PATTERN.search(normalized_title):
            return True
        if not _UHD_PATTERN.search(normalized_title):
            return False
        return not bool(_HD_RESOLUTION_PATTERN.search(normalized_title))

    pattern = _SEARCH_SUBCATEGORY_TITLE_FILTERS.get(behavior_category)
    if not pattern:
        return True
    return bool(pattern.search(normalized_title))


def determine_search_categories(request_from, cat_param=None):
    """
    Determine one or more numeric search categories from the cat parameter.

    Behavior:
    - Valid comma-separated categories are returned as a sorted unique list.
    - If no valid categories are provided, fallback to client-based default.
    """
    if cat_param:
        valid_categories = set()
        invalid_tokens = []

        for raw_cat in str(cat_param).split(","):
            raw_cat = raw_cat.strip()
            if not raw_cat:
                continue
            try:
                cat_id = int(raw_cat)
            except ValueError:
                invalid_tokens.append(raw_cat)
                continue

            if search_category_exists(cat_id):
                valid_categories.add(cat_id)
            else:
                invalid_tokens.append(raw_cat)

        if valid_categories:
            categories = sorted(valid_categories)
            if len(categories) > 1:
                debug(
                    f"Resolved multi-category search request <g>{cat_param}</g> to <g>{','.join(str(c) for c in categories)}</g>"
                )
            return categories

        if invalid_tokens:
            warn(
                f"Invalid search categories provided: <r>{','.join(invalid_tokens)}</r>. Falling back to client default."
            )

    # Fallback to deriving from user agent
    client_type = extract_client_type(request_from)
    if client_type == "radarr":
        return [SEARCH_CAT_MOVIES]
    elif client_type == "lidarr":
        return [SEARCH_CAT_MUSIC]
    elif client_type == "magazarr":
        return [SEARCH_CAT_BOOKS]
    elif client_type == "sonarr":
        return [SEARCH_CAT_SHOWS]
    else:
        warn(f"Unknown client type '{client_type}' from '{request_from}'")
        return []


def order_search_categories_for_execution(categories):
    """
    Order requested categories so that each cache family runs from lowest ID first.

    This makes the least restrictive category in each family populate cache first.
    """
    ordered = []
    for _, category_ids in get_search_cache_family_groups(categories):
        ordered.extend(category_ids)
    return ordered


def determine_search_category(request_from, cat_param=None):
    """
    Determine the numeric search category based on the client type or cat parameter.
    Handles default and custom categories.
    """
    categories = determine_search_categories(request_from, cat_param)
    if not categories:
        return None
    return categories[0]


def extract_client_type(request_from):
    """
    Extract client type from User-Agent, stripping version info.

    Examples:
        "Radarr/6.0.4.10291 (alpine 3.23.2)" → "radarr"
        "Sonarr/4.0.0.123" → "sonarr"
        "Magazarr/1.0" → "magazarr"
    """
    if not request_from:
        return "unknown"

    # Extract the client name before the version (first part before '/')
    client = request_from.split("/")[0].lower().strip()

    # Normalize known clients
    if "radarr" in client:
        return "radarr"
    elif "sonarr" in client:
        return "sonarr"
    elif "lidarr" in client:
        return "lidarr"
    elif "magazarr" in client:
        return "magazarr"

    return client


def convert_to_mb(item):
    size = float(item["size"])
    unit = item["sizeunit"].upper()

    if unit == "B":
        size_b = size
    elif unit == "KB":
        size_b = size * 1024
    elif unit == "MB":
        size_b = size * 1024 * 1024
    elif unit == "GB":
        size_b = size * 1024 * 1024 * 1024
    elif unit == "TB":
        size_b = size * 1024 * 1024 * 1024 * 1024
    else:
        raise ValueError(
            f"Unsupported size unit {item['name']} {item['size']} {item['sizeunit']}"
        )

    size_mb = size_b / (1024 * 1024)
    return int(size_mb)


def replace_umlauts(text):
    """
    Replace German umlauts with their ASCII equivalents.
    """
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }

    for umlaut, replacement in replacements.items():
        text = text.replace(umlaut, replacement)

    return text


def sanitize_title(title: str) -> str:
    title = replace_umlauts(title)

    title = title.encode("ascii", errors="ignore").decode()

    # Replace slashes and spaces with dots
    title = title.replace("/", "").replace(" ", ".")
    title = title.strip(".")  # no leading/trailing dots
    title = title.replace(".-.", "-")  # .-. → -

    # Finally, drop any chars except letters, digits, dots, hyphens, ampersands
    title = re.sub(r"[^A-Za-z0-9.\-&]", "", title)

    # remove any repeated dots
    title = re.sub(r"\.{2,}", ".", title)
    return title


def sanitize_string(s):
    s = s.lower()

    # Remove dots / pluses
    s = s.replace(".", " ")
    s = s.replace("+", " ")
    s = s.replace("_", " ")
    s = s.replace("-", " ")

    # Umlauts
    s = replace_umlauts(s)

    # Remove special characters
    s = re.sub(r"[^a-zA-Z0-9\s]", "", s)

    # Remove season and episode patterns
    s = re.sub(r"\bs\d{1,3}(e\d{1,3})?\b", "", s)

    # Remove German and English articles
    articles = r"\b(?:der|die|das|ein|eine|einer|eines|einem|einen|the|a|an|and)\b"
    s = re.sub(articles, "", s, count=0, flags=re.IGNORECASE)

    # Replace obsolete titles
    s = s.replace("navy cis", "ncis")

    # Remove extra whitespace
    s = " ".join(s.split())

    return s


def search_string_in_sanitized_title(search_string, title):
    sanitized_search_string = sanitize_string(search_string)
    sanitized_title = sanitize_string(title)

    search_regex = r"\b.+\b".join(
        [re.escape(s) for s in sanitized_search_string.split(" ")]
    )
    # Use word boundaries to ensure full word/phrase match
    if re.search(rf"\b{search_regex}\b", sanitized_title):
        trace(f"Matched search string: {search_regex} with title: {sanitized_title}")
        return True
    else:
        trace(
            f"Skipping {title} as it doesn't match search string: {sanitized_search_string}"
        )
        return False


def is_imdb_id(search_string):
    if bool(re.fullmatch(r"tt\d{7,}", search_string)):
        return search_string
    else:
        return None


def normalize_optional_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def match_in_title(title: str, season: int = None, episode: int = None) -> bool:
    season = normalize_optional_int(season)
    episode = normalize_optional_int(episode)

    pattern = re.compile(
        r"(?i)(?:\.|^)[sS](\d+)(?:-(\d+))?"  # season or season‑range
        r"(?:[eE](\d+)(?:-(?:[eE]?)(\d+))?)?"  # episode or episode‑range
        r"(?=[\.-]|$)"
    )

    matches = pattern.findall(title)
    if not matches:
        return False

    for s_start, s_end, e_start, e_end in matches:
        se_start, se_end = int(s_start), int(s_end or s_start)

        # if a season was requested, ensure it falls in the range
        if season is not None and not (se_start <= season <= se_end):
            continue

        # if no episode requested, only accept if the title itself had no episode tag
        if episode is None:
            if not e_start:
                return True
            else:
                # title did specify an episode — skip this match
                continue

        # episode was requested, so title must supply one
        if not e_start:
            continue

        ep_start, ep_end = int(e_start), int(e_end or e_start)
        if ep_start <= episode <= ep_end:
            return True

    return False


_DATE_NUMBERING_IGNORED_ARTICLES = {
    "a",
    "an",
    "and",
    "das",
    "der",
    "die",
    "the",
}
_DATE_NUMBERING_SCHEDULE_WORDS = {
    "friday",
    "monday",
    "night",
    "saturday",
    "sunday",
    "thursday",
    "tuesday",
    "wednesday",
}
_DATE_NUMBERING_IGNORED_TITLE_WORDS = (
    _DATE_NUMBERING_IGNORED_ARTICLES | _DATE_NUMBERING_SCHEDULE_WORDS
)


def parse_episode_date(season, episode):
    """Return a validated date for Sonarr's year + MM/DD numbering shape."""
    if not re.fullmatch(r"\d{4}", str(season or "")):
        return None

    parts = str(episode or "").split("/")
    if len(parts) != 2:
        return None

    try:
        return date(int(season), int(parts[0]), int(parts[1]))
    except (TypeError, ValueError):
        return None


def _date_numbering_date_pattern(episode_date):
    return re.compile(
        rf"(?<!\d){episode_date:%Y}[\s.-]+{episode_date:%m}[\s.-]+"
        rf"{episode_date:%d}(?!\d)"
    )


def date_numbering_title_tokens(
    value, episode_date=None, preserve_schedule_words=False
):
    value = str(value or "")
    if episode_date is not None:
        value = _date_numbering_date_pattern(episode_date).sub(" ", value)

    normalized = replace_umlauts(html.unescape(value)).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    tokens = normalized.split()
    ignored_words = (
        _DATE_NUMBERING_IGNORED_ARTICLES
        if preserve_schedule_words
        else _DATE_NUMBERING_IGNORED_TITLE_WORDS
    )
    meaningful_tokens = [token for token in tokens if token not in ignored_words]
    if meaningful_tokens:
        return meaningful_tokens

    return [token for token in tokens if token not in _DATE_NUMBERING_IGNORED_ARTICLES]


def date_numbering_title_matches(title, search_string, episode_date=None):
    search_tokens = date_numbering_title_tokens(search_string, episode_date)
    if not search_tokens:
        return False
    preserve_schedule_words = set(search_tokens).issubset(
        _DATE_NUMBERING_SCHEDULE_WORDS
    )
    title_tokens = date_numbering_title_tokens(
        title,
        episode_date,
        preserve_schedule_words=preserve_schedule_words,
    )
    return all(
        title_tokens.count(token) >= search_tokens.count(token)
        for token in set(search_tokens)
    )


def date_numbering_release_matches(title, search_string, episode_date):
    if episode_date is None:
        return False

    date_pattern = _date_numbering_date_pattern(episode_date)
    if not date_pattern.search(str(title or "")):
        return False
    return bool(
        is_imdb_id(search_string)
        or date_numbering_title_matches(title, search_string, episode_date)
    )


def _date_numbering_case_variant(value):
    words = str(value or "").split()
    normalized = []
    changed = False
    for word in words:
        if any(char.islower() for char in word) and any(
            char.isupper() for char in word[1:]
        ):
            word = word[:1] + word[1:].lower()
            changed = True
        normalized.append(word)
    return " ".join(normalized) if changed else ""


def date_numbering_title_search_strings(search_string):
    """Build generic title variants for broad date-numbered source searches."""
    search_string = " ".join(str(search_string or "").split())
    if not search_string:
        return [search_string]

    title_variants = [search_string]
    words = search_string.split()
    if re.fullmatch(r"[A-Z0-9]{2,5}", words[0]):
        title_variants.insert(0, words[0])

    compact_words = [
        word
        for word in words
        if re.sub(r"[^a-z0-9]+", "", word.lower()) not in _DATE_NUMBERING_SCHEDULE_WORDS
    ]
    if len(compact_words) >= 2 and compact_words != words:
        title_variants.append(" ".join(compact_words))

    for value in list(title_variants):
        case_variant = _date_numbering_case_variant(value)
        if case_variant and case_variant not in title_variants:
            title_variants.append(case_variant)

    return title_variants


def date_numbering_search_strings(search_string, episode_date):
    """Build generic title/date variants without series-specific aliases."""
    if episode_date is None:
        return [" ".join(str(search_string or "").split())]

    title_variants = date_numbering_title_search_strings(search_string)

    search_strings = list(title_variants)
    for candidate in (
        episode_date,
        episode_date - timedelta(days=1),
        episode_date + timedelta(days=1),
    ):
        for title_variant in title_variants:
            for date_variant in (
                f"{candidate:%Y %m %d}",
                f"{candidate:%Y-%m-%d}",
                f"{candidate:%Y.%m.%d}",
            ):
                value = f"{title_variant} {date_variant}"
                if value not in search_strings:
                    search_strings.append(value)

    return search_strings


def canonicalize_date_numbered_title(title, search_string, episode_date):
    if is_imdb_id(search_string) or not date_numbering_release_matches(
        title, search_string, episode_date
    ):
        return title

    date_match = re.search(
        rf"(?<!\d){episode_date:%Y}[\s.-]+{episode_date:%m}[\s.-]+"
        rf"{episode_date:%d}(?!\d)",
        str(title or ""),
    )
    if not date_match:
        return title

    canonical_prefix = re.sub(r"[^\w]+", ".", str(search_string)).strip(".")
    suffix = str(title)[date_match.start() :].lstrip(" .-_")
    return f"{canonical_prefix}.{suffix}" if canonical_prefix and suffix else title


def is_valid_release(
    title: str,
    search_category: int,
    search_string: str,
    season: int = None,
    episode: int = None,
    episode_date: date = None,
) -> bool:
    """
    Return True if the given release title is valid for the given search parameters.
    - title: the release title to test
    - search_category: numeric search category, 2000 for movies, 5000 for tv shows
    - search_string: the original search phrase (could be an IMDb id or plain text)
    - season: desired season number (or None)
    - episode: desired episode number (or None)
    - episode_date: validated date for a date-numbered TV episode (or None)
    """
    try:
        is_movie_search = search_category // 1000 * 1000 == SEARCH_CAT_MOVIES
        is_tv_search = search_category // 1000 * 1000 == SEARCH_CAT_SHOWS
        is_docs_search = search_category // 1000 * 1000 == SEARCH_CAT_BOOKS
        is_music_search = search_category // 1000 * 1000 == SEARCH_CAT_MUSIC
        is_xxx_search = search_category // 1000 * 1000 == SEARCH_CAT_XXX

        # if search string is NOT an imdb id, require a title match
        if not is_docs_search and not is_imdb_id(search_string):
            title_matches = (
                date_numbering_title_matches(title, search_string, episode_date)
                if is_tv_search and episode_date is not None
                else search_string_in_sanitized_title(search_string, title)
            )
            if not title_matches:
                trace(
                    "Skipping {title!r} as it doesn't match sanitized "
                    "search string: {search_string!r}",
                    title=title,
                    search_string=search_string,
                )
                return False

        # if it's a movie search, don't allow any TV show titles (check for NO season or episode tags in the title)
        if is_movie_search:
            if not MOVIE_REGEX.match(title):
                trace(
                    "Skipping {title!r} as title doesn't match movie regex: {pattern!r}",
                    title=title,
                    pattern=MOVIE_REGEX.pattern,
                )
                return False
            return True

        # if it's a TV show search, don't allow any movies (check for season or episode tags in the title)
        if is_tv_search:
            if episode_date is not None:
                if not date_numbering_release_matches(
                    title, search_string, episode_date
                ):
                    trace(
                        "Skipping {title!r} as it doesn't match date {episode_date}",
                        title=title,
                        episode_date=episode_date,
                    )
                    return False
                return True

            # must have some S/E tag present
            if not SEASON_EP_REGEX.search(title):
                trace(
                    "Skipping {title!r} as title doesn't match TV show regex: {pattern!r}",
                    title=title,
                    pattern=SEASON_EP_REGEX.pattern,
                )
                return False
            # if caller specified a season or episode, double‑check the match
            if season is not None or episode is not None:
                if not match_in_title(title, season, episode):
                    trace(
                        "Skipping {title!r} as it doesn't match season "
                        "{season} and episode {episode}",
                        title=title,
                        season=season,
                        episode=episode,
                    )
                    return False
            return True

        # if it's a document search, it should not contain Movie or TV show tags
        if is_docs_search:
            # must NOT have any S/E tag present
            if SEASON_EP_REGEX.search(title):
                trace(
                    "Skipping {title!r} as title matches TV show regex: {pattern!r}",
                    title=title,
                    pattern=SEASON_EP_REGEX.pattern,
                )
                return False
            return True

        # if it's a music search, it should not contain Movie or TV show tags
        if is_music_search:
            # must NOT have any S/E tag present
            if SEASON_EP_REGEX.search(title):
                trace(
                    "Skipping {title!r} as title matches TV show regex: {pattern!r}",
                    title=title,
                    pattern=SEASON_EP_REGEX.pattern,
                )
                return False
            return True

        if is_xxx_search:
            return True

        # unknown search source — reject by default
        debug(f"Skipping {title!r} as search category is unknown: {search_category!r}")
        return False

    except Exception as e:
        # log exception message and short stack trace
        tb = traceback.format_exc()
        debug(
            f"Exception in is_valid_release: {e!r}\n{tb}"
            f"is_valid_release called with "
            f"title={title!r}, search_category={search_category!r}, "
            f"search_string={search_string!r}, season={season!r}, episode={episode!r}"
        )
        return False


def normalize_magazine_title(title: str) -> str:
    """
    Massage magazine titles so Magazarr's parser can pick up dates reliably:
    - Convert date-like patterns into space-delimited numeric tokens (YYYY MM DD or YYYY MM).
    - Handle malformed "DD.YYYY.YYYY" cases (e.g., 04.2006.2025 → 2025 06 04).
    - Convert two-part month-year like "3.25" into YYYY MM.
    - Convert "No/Nr/Sonderheft X.YYYY" when X≤12 into YYYY MM.
    - Preserve pure issue/volume prefixes and other digit runs untouched.
    """
    title = title.strip()

    # 0) Bug: DD.YYYY.YYYY -> treat second YYYY's last two digits as month
    def repl_bug(match):
        d = int(match.group(1))
        m_hint = match.group(2)
        y = int(match.group(3))
        m = int(m_hint[-2:])
        try:
            date(y, m, d)
            return f"{y:04d} {m:02d} {d:02d}"
        except ValueError:
            return match.group(0)

    title = re.sub(r"\b(\d{1,2})\.(20\d{2})\.(20\d{2})\b", repl_bug, title)

    # 1) DD.MM.YYYY -> "YYYY MM DD"
    def repl_dmy(match):
        d, m, y = map(int, match.groups())
        try:
            date(y, m, d)
            return f"{y:04d} {m:02d} {d:02d}"
        except ValueError:
            return match.group(0)

    title = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", repl_dmy, title)

    # 2) DD[.]? MonthName YYYY (optional 'vom') -> "YYYY MM DD"
    def repl_dmony(match):
        d = int(match.group(1))
        name = match.group(2)
        y = int(match.group(3))
        mm = MONTHS_MAP.get(name.lower())
        if mm:
            try:
                date(y, mm, d)
                return f"{y:04d} {mm:02d} {d:02d}"
            except ValueError:
                pass
        return match.group(0)

    title = re.sub(
        r"\b(?:vom\s*)?(\d{1,2})\.?\s+([A-Za-zÄÖÜäöüß]+)\s+(\d{4})\b",
        repl_dmony,
        title,
        flags=re.IGNORECASE,
    )

    # 3) MonthName YYYY -> "YYYY MM"
    def repl_mony(match):
        name = match.group(1)
        y = int(match.group(2))
        mm = MONTHS_MAP.get(name.lower())
        if mm:
            try:
                date(y, mm, 1)
                return f"{y:04d} {mm:02d}"
            except ValueError:
                pass
        return match.group(0)

    title = re.sub(
        r"\b([A-Za-zÄÖÜäöüß]+)\s+(\d{4})\b", repl_mony, title, flags=re.IGNORECASE
    )

    # 4) YYYYMMDD -> "YYYY MM DD"
    def repl_ymd(match):
        y = int(match.group(1))
        m = int(match.group(2))
        d = int(match.group(3))
        try:
            date(y, m, d)
            return f"{y:04d} {m:02d} {d:02d}"
        except ValueError:
            return match.group(0)

    title = re.sub(
        r"\b(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b", repl_ymd, title
    )

    # 5) YYYYMM -> "YYYY MM"
    def repl_ym(match):
        y = int(match.group(1))
        m = int(match.group(2))
        try:
            date(y, m, 1)
            return f"{y:04d} {m:02d}"
        except ValueError:
            return match.group(0)

    title = re.sub(r"\b(20\d{2})(0[1-9]|1[0-2])\b", repl_ym, title)

    # 6) X.YY (month.two-digit-year) -> "YYYY MM" (e.g., 3.25 -> 2025 03)
    def repl_my2(match):
        mm = int(match.group(1))
        yy = int(match.group(2))
        y = 2000 + yy
        if 1 <= mm <= 12:
            try:
                date(y, mm, 1)
                return f"{y:04d} {mm:02d}"
            except ValueError:
                pass
        return match.group(0)

    title = re.sub(r"\b([1-9]|1[0-2])\.(\d{2})\b", repl_my2, title)

    # 7) No/Nr/Sonderheft <1-12>.<YYYY> -> "YYYY MM"
    def repl_nmy(match):
        num = int(match.group(1))
        y = int(match.group(2))
        if 1 <= num <= 12:
            try:
                date(y, num, 1)
                return f"{y:04d} {num:02d}"
            except ValueError:
                pass
        return match.group(0)

    title = re.sub(
        r"\b(?:No|Nr|Sonderheft)\s*(\d{1,2})\.(\d{4})\b",
        repl_nmy,
        title,
        flags=re.IGNORECASE,
    )

    return title


def get_recently_searched(shared_state, context, timeout_seconds):
    recently_searched = shared_state.values.get(context, {})
    threshold = datetime.now() - timedelta(seconds=timeout_seconds)
    keys_to_remove = [
        key
        for key, value in recently_searched.items()
        if value["timestamp"] <= threshold
    ]
    for key in keys_to_remove:
        debug(f"Removing '{key}' from recently searched memory ({context})...")
        del recently_searched[key]
    return recently_searched


def download_package(links, title, password, package_id, shared_state):
    links = [sanitize_url(link) for link in links]

    destination_folder = _quasarr_destination_folder(package_id)

    def submit(device):
        return device.linkgrabber.add_links(
            params=[
                {
                    "autostart": False,
                    "links": json.dumps(links),
                    "packageName": title,
                    "extractPassword": password,
                    "priority": "DEFAULT",
                    "downloadPassword": password,
                    "destinationFolder": destination_folder,
                    "comment": package_id,
                    "overwritePackagizerRules": True,
                }
            ]
        )

    downloaded = shared_state.run_device_request(
        "submit links to linkgrabber",
        submit,
        default=False,
    )
    return downloaded


def _quasarr_destination_folder(package_id):
    """Return the JDownloader destinationFolder for a Quasarr package.

    Two independent, opt-in environment variables shape the path; with neither
    set the result is the historical ``Quasarr/<jd:packagename>`` (unchanged):

      * ``DOWNLOAD_FOLDER`` -- base folder Quasarr downloads into. Relative to
        JDownloader's default download directory, or an absolute path. Defaults
        to ``Quasarr``. Set it empty to drop the ``Quasarr`` level entirely.
      * ``CATEGORY_SUBFOLDERS`` (true/false) -- insert the package's download
        category (movies/tv/music/...) as a subfolder, grouping downloads by type.

    The category is read from the package id (never from disk); unknown or
    non-Quasarr packages fall back to the base-only path.
    """
    package_var = "<jd:packagename>"

    raw_base = os.environ.get("DOWNLOAD_FOLDER")
    base = "Quasarr" if raw_base is None else raw_base.strip().rstrip("/")

    parts = []
    if base:
        parts.append(base)

    if os.environ.get("CATEGORY_SUBFOLDERS", "").strip().lower() in ("1", "true", "yes", "on"):
        # Local import avoids a module-level storage <-> providers import cycle.
        from quasarr.storage.categories import get_download_category_from_package_id
        category = get_download_category_from_package_id(package_id)
        if category and category != "not_quasarr":
            parts.append(category)

    parts.append(package_var)
    return "/".join(parts)


def sanitize_url(url: str) -> str:
    # normalize first
    url = unicodedata.normalize("NFKC", url)

    # 1) real control characters (U+0000–U+001F, U+007F–U+009F)
    _REAL_CTRL_RE = re.compile(r"[\u0000-\u001f\u007f-\u009f]")

    # 2) *literal* escaped unicode junk: \u0010, \x10, repeated variants
    _ESCAPED_CTRL_RE = re.compile(r"(?:\\u00[0-1][0-9a-fA-F]|\\x[0-1][0-9a-fA-F])")

    # remove literal escaped control sequences like "\u0010"
    url = _ESCAPED_CTRL_RE.sub("", url)

    # remove actual control characters if already decoded
    url = _REAL_CTRL_RE.sub("", url)

    return url.strip()
