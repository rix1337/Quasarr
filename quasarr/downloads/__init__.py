# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import hashlib
import json
import re

from quasarr.downloads.linkcrypters.hide import decrypt_links_if_hide
from quasarr.downloads.packages import get_packages
from quasarr.downloads.sources.al import get_al_download_links
from quasarr.downloads.sources.by import get_by_download_links
from quasarr.downloads.sources.dd import get_dd_download_links
from quasarr.downloads.sources.dj import get_dj_download_links
from quasarr.downloads.sources.dl import get_dl_download_links
from quasarr.downloads.sources.dt import get_dt_download_links
from quasarr.downloads.sources.dw import get_dw_download_links
from quasarr.downloads.sources.he import get_he_download_links
from quasarr.downloads.sources.mb import get_mb_download_links
from quasarr.downloads.sources.nk import get_nk_download_links
from quasarr.downloads.sources.nx import get_nx_download_links
from quasarr.downloads.sources.sf import get_sf_download_links
from quasarr.downloads.sources.sj import get_sj_download_links
from quasarr.downloads.sources.sl import get_sl_download_links
from quasarr.downloads.sources.wd import get_wd_download_links
from quasarr.downloads.sources.wx import get_wx_download_links
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import info
from quasarr.providers.notifications import send_discord_message
from quasarr.providers.statistics import StatsHelper
from quasarr.providers.utils import filter_offline_links

# =============================================================================
# CRYPTER CONFIGURATION
# =============================================================================

# Patterns match crypter name only - TLDs may change
AUTO_DECRYPT_PATTERNS = {
    "hide": re.compile(r"hide\.", re.IGNORECASE),
}

PROTECTED_PATTERNS = {
    "filecrypt": re.compile(r"filecrypt\.", re.IGNORECASE),
    "tolink": re.compile(r"tolink\.", re.IGNORECASE),
    "keeplinks": re.compile(r"keeplinks\.", re.IGNORECASE),
}

# Source key -> getter function mapping
# All getters have signature: (shared_state, url, mirror, title, password)
# AL uses password as release_id, others ignore it
SOURCE_GETTERS = {
    "al": get_al_download_links,
    "by": get_by_download_links,
    "dd": get_dd_download_links,
    "dj": get_dj_download_links,
    "dl": get_dl_download_links,
    "dt": get_dt_download_links,
    "dw": get_dw_download_links,
    "he": get_he_download_links,
    "mb": get_mb_download_links,
    "nk": get_nk_download_links,
    "nx": get_nx_download_links,
    "sf": get_sf_download_links,
    "sj": get_sj_download_links,
    "sl": get_sl_download_links,
    "wd": get_wd_download_links,
    "wx": get_wx_download_links,
}


# =============================================================================
# DETERMINISTIC PACKAGE ID GENERATION
# =============================================================================


def extract_client_type(request_from):
    """
    Extract client type from User-Agent, stripping version info.

    Examples:
        "Radarr/6.0.4.10291 (alpine 3.23.2)" → "radarr"
        "Sonarr/4.0.0.123" → "sonarr"
        "LazyLibrarian/1.0" → "lazylibrarian"
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
    elif "lazylibrarian" in client:
        return "lazylibrarian"

    return client


def generate_deterministic_package_id(title, source_key, client_type):
    """
    Generate a deterministic package ID from title, source, and client type.

    The same combination of (title, source_key, client_type) will ALWAYS produce
    the same package_id, allowing clients to reliably blocklist erroneous releases.

    Args:
        title: Release title (e.g., "Movie.Name.2024.1080p.BluRay")
        source_key: Source identifier/hostname shorthand (e.g., "nx", "dl", "al")
        client_type: Client type without version (e.g., "radarr", "sonarr", "lazylibrarian")

    Returns:
        Deterministic package ID in format: Quasarr_{category}_{hash32}
    """
    # Normalize inputs for consistency
    normalized_title = title.strip()
    normalized_source = source_key.lower().strip() if source_key else "unknown"
    normalized_client = client_type.lower().strip() if client_type else "unknown"

    # Category mapping (for compatibility with existing package ID format)
    category_map = {"lazylibrarian": "docs", "radarr": "movies", "sonarr": "tv"}
    category = category_map.get(normalized_client, "tv")

    # Create deterministic hash from combination using SHA256
    hash_input = f"{normalized_title}|{normalized_source}|{normalized_client}"
    hash_bytes = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    # Use first 32 characters for good collision resistance (128-bit)
    return f"Quasarr_{category}_{hash_bytes[:32]}"


# =============================================================================
# LINK CLASSIFICATION
# =============================================================================


def detect_crypter(url):
    """Returns (crypter_name, 'auto'|'protected') or (None, None)."""
    for name, pattern in AUTO_DECRYPT_PATTERNS.items():
        if pattern.search(url):
            return name, "auto"
    for name, pattern in PROTECTED_PATTERNS.items():
        if pattern.search(url):
            return name, "protected"
    return None, None


def is_junkies_link(url, shared_state):
    """Check if URL is a junkies (sj/dj) link."""
    sj = shared_state.values["config"]("Hostnames").get("sj")
    dj = shared_state.values["config"]("Hostnames").get("dj")
    url_lower = url.lower()
    return (sj and sj.lower() in url_lower) or (dj and dj.lower() in url_lower)


def classify_links(links, shared_state):
    """
    Classify links into direct/auto/protected categories.
    Direct = anything that's not a known crypter or junkies link.
    Mirror names from source are preserved.
    """
    classified = {"direct": [], "auto": [], "protected": []}

    for link in links:
        url = link[0]

        if is_junkies_link(url, shared_state):
            classified["protected"].append(link)
            continue

        crypter, crypter_type = detect_crypter(url)
        if crypter_type == "auto":
            classified["auto"].append(link)
        elif crypter_type == "protected":
            classified["protected"].append(link)
        else:
            # Not a known crypter = direct hoster link
            classified["direct"].append(link)

    return classified


# =============================================================================
# LINK PROCESSING
# =============================================================================


def handle_direct_links(shared_state, links, title, password, package_id):
    """Send direct hoster links to JDownloader."""
    urls = [link[0] for link in links]
    info(f"Sending {len(urls)} direct download links for {title}")

    if shared_state.download_package(urls, title, password, package_id):
        StatsHelper(shared_state).increment_package_with_links(urls)
        return {"success": True}
    return {
        "success": False,
        "reason": f"Failed to add {len(urls)} links to linkgrabber",
    }


def handle_auto_decrypt_links(shared_state, links, title, password, package_id):
    """Decrypt hide.cx links and send to JDownloader."""
    result = decrypt_links_if_hide(shared_state, links)

    if result.get("status") != "success":
        return {"success": False, "reason": "Auto-decrypt failed"}

    decrypted_urls = result.get("results", [])
    if not decrypted_urls:
        return {"success": False, "reason": "No links decrypted"}

    info(f"Decrypted {len(decrypted_urls)} download links for {title}")

    if shared_state.download_package(decrypted_urls, title, password, package_id):
        StatsHelper(shared_state).increment_package_with_links(decrypted_urls)
        return {"success": True}
    return {"success": False, "reason": "Failed to add decrypted links to linkgrabber"}


def store_protected_links(
    shared_state, links, title, password, package_id, size_mb=None, original_url=None
):
    """Store protected links for CAPTCHA UI."""
    blob_data = {
        "title": title,
        "links": links,
        "password": password,
        "size_mb": size_mb,
    }
    if original_url:
        blob_data["original_url"] = original_url

    shared_state.values["database"]("protected").update_store(
        package_id, json.dumps(blob_data)
    )
    info(
        f'CAPTCHA-Solution required for "{title}" at: "{shared_state.values["external_address"]}/captcha"'
    )
    return {"success": True}


def process_links(
    shared_state,
    source_result,
    title,
    password,
    package_id,
    imdb_id,
    source_url,
    size_mb,
    label,
):
    """
    Central link processor with priority: direct → auto-decrypt → protected.
    If ANY direct links exist, use them and ignore crypted fallbacks.
    """
    if not source_result:
        return fail(
            title,
            package_id,
            shared_state,
            reason=f'Source returned no data for "{title}" on {label} - "{source_url}"',
        )

    links = source_result.get("links", [])
    password = source_result.get("password") or password
    imdb_id = imdb_id or source_result.get("imdb_id")
    title = source_result.get("title") or title

    if not links:
        return fail(
            title,
            package_id,
            shared_state,
            reason=f'No links found for "{title}" on {label} - "{source_url}"',
        )

    # Filter out 404 links
    valid_links = [link for link in links if "/404.html" not in link[0]]
    if not valid_links:
        return fail(
            title,
            package_id,
            shared_state,
            reason=f'All links are offline or IP is banned for "{title}" on {label} - "{source_url}"',
        )
    links = valid_links

    # Filter out verifiably offline links
    links = filter_offline_links(links, shared_state=shared_state, log_func=info)
    if not links:
        return fail(
            title,
            package_id,
            shared_state,
            reason=f'All verifiable links are offline for "{title}" on {label} - "{source_url}"',
        )

    classified = classify_links(links, shared_state)

    # PRIORITY 1: Direct hoster links
    if classified["direct"]:
        info(f"Found {len(classified['direct'])} direct hoster links for {title}")
        send_discord_message(
            shared_state,
            title=title,
            case="unprotected",
            imdb_id=imdb_id,
            source=source_url,
        )
        result = handle_direct_links(
            shared_state, classified["direct"], title, password, package_id
        )
        if result["success"]:
            return {"success": True, "title": title}
        return fail(title, package_id, shared_state, reason=result.get("reason"))

    # PRIORITY 2: Auto-decryptable (hide.cx)
    if classified["auto"]:
        info(f"Found {len(classified['auto'])} auto-decryptable links for {title}")
        result = handle_auto_decrypt_links(
            shared_state, classified["auto"], title, password, package_id
        )
        if result["success"]:
            send_discord_message(
                shared_state,
                title=title,
                case="unprotected",
                imdb_id=imdb_id,
                source=source_url,
            )
            return {"success": True, "title": title}
        info(f"Auto-decrypt failed for {title}, falling back to manual CAPTCHA...")
        classified["protected"].extend(classified["auto"])

    # PRIORITY 3: Protected (filecrypt, tolink, keeplinks, junkies)
    if classified["protected"]:
        info(f"Found {len(classified['protected'])} protected links for {title}")
        send_discord_message(
            shared_state,
            title=title,
            case="captcha",
            imdb_id=imdb_id,
            source=source_url,
        )
        store_protected_links(
            shared_state,
            classified["protected"],
            title,
            password,
            package_id,
            size_mb=size_mb,
            original_url=source_url,
        )
        return {"success": True, "title": title}

    return fail(
        title,
        package_id,
        shared_state,
        reason=f'No usable links found for "{title}" on {label} - "{source_url}"',
    )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def package_id_exists(shared_state, package_id):
    # DB checks
    if shared_state.get_db("protected").retrieve(package_id):
        return True
    if shared_state.get_db("failed").retrieve(package_id):
        return True

    data = get_packages(shared_state) or {}

    for section in ("queue", "history"):
        for pkg in data.get(section, []) or []:
            if pkg.get("nzo_id") == package_id:
                return True

    return False


def download(
    shared_state,
    request_from,
    title,
    url,
    mirror,
    size_mb,
    password,
    imdb_id=None,
    source_key=None,
):
    """
    Main download entry point.

    Args:
        shared_state: Application shared state
        request_from: User-Agent string (e.g., "Radarr/6.0.4.10291")
        title: Release title
        url: Source URL
        mirror: Preferred mirror/hoster
        size_mb: Size in MB
        password: Archive password
        imdb_id: IMDb ID (optional)
        source_key: Hostname shorthand from search (e.g., "nx", "dl"). If not provided,
                    will be derived from URL matching against configured hostnames.
    """
    if imdb_id and imdb_id.lower() == "none":
        imdb_id = None

    config = shared_state.values["config"]("Hostnames")

    # Extract client type (without version) for deterministic hashing
    client_type = extract_client_type(request_from)

    # Find matching source - all getters have unified signature
    source_result = None
    label = None
    detected_source_key = None

    for key, getter in SOURCE_GETTERS.items():
        hostname = config.get(key)
        if hostname and hostname.lower() in url.lower():
            try:
                source_result = getter(shared_state, url, mirror, title, password)
                if source_result and source_result.get("links"):
                    clear_hostname_issue(key)
            except Exception as e:
                info(f"Error getting download links from {key.upper()}: {e}")
                mark_hostname_issue(key, "download", str(e))
                source_result = None
            label = key.upper()
            detected_source_key = key
            break

    # No source matched - check if URL is a known crypter directly
    if source_result is None:
        crypter, crypter_type = detect_crypter(url)
        if crypter_type:
            # For direct crypter URLs, we only know the crypter type, not the hoster inside
            source_result = {"links": [[url, crypter]]}
            label = crypter.upper()
            detected_source_key = crypter

    # Use provided source_key if available, otherwise use detected one
    # This ensures we use the authoritative source from the search results
    final_source_key = source_key if source_key else detected_source_key

    # Generate DETERMINISTIC package_id
    package_id = generate_deterministic_package_id(title, final_source_key, client_type)

    # Skip Download if package_id already exists
    if package_id_exists(shared_state, package_id):
        info(f"Package {package_id} already exists. Skipping download!")
        return {"success": True, "package_id": package_id, "title": title}

    if source_result is None:
        info(f'Could not find matching source for "{title}" - "{url}"')
        StatsHelper(shared_state).increment_failed_downloads()
        return {"success": False, "package_id": package_id, "title": title}

    result = process_links(
        shared_state,
        source_result,
        title,
        password,
        package_id,
        imdb_id,
        url,
        size_mb,
        label,
    )
    return {"package_id": package_id, **result}


def fail(title, package_id, shared_state, reason="Unknown error"):
    """Mark download as failed."""
    try:
        info(f"Reason for failure: {reason}")
        StatsHelper(shared_state).increment_failed_downloads()
        blob = json.dumps({"title": title, "error": reason})
        shared_state.get_db("failed").store(package_id, json.dumps(blob))
        info(f'Package "{title}" marked as failed!')
    except Exception as e:
        info(f'Error marking package "{package_id}" as failed: {e}')
    return {"success": False, "title": title}
