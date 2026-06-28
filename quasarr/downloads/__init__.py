# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import hashlib
import json

from quasarr.constants import (
    AUTO_DECRYPT_PATTERNS,
    CLIENT_DOWNLOAD_CATEGORY_FALLBACK_MAP,
    PROTECTED_PATTERNS,
)
from quasarr.downloads.linkcrypters.hide import decrypt_links_if_hide
from quasarr.downloads.mirror_filters import filter_final_download_urls
from quasarr.downloads.packages import get_packages
from quasarr.downloads.sources import get_sources as get_download_sources
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import info, warn
from quasarr.providers.notifications import (
    send_notification,
    send_tracked_notification,
    update_release_notification,
)
from quasarr.providers.notifications.helpers.notification_types import NotificationType
from quasarr.providers.statistics import StatsHelper
from quasarr.providers.utils import (
    download_package,
    extract_client_type,
    filter_offline_links,
    normalize_download_title,
)
from quasarr.storage.categories import (
    download_category_exists,
    get_download_category_from_package_id,
    get_download_category_mirrors,
)

# =============================================================================
# DETERMINISTIC PACKAGE ID GENERATION
# =============================================================================


def generate_deterministic_package_id(
    title, source_key, client_type, download_category
):
    """
    Generate a deterministic package ID from title, source, and client type.

    The same combination of (title, source_key, client_type) will ALWAYS produce
    the same package_id, allowing clients to reliably blocklist erroneous releases.

    Args:
        title: Release title (e.g., "Movie.Name.2024.1080p.BluRay")
        source_key: Source identifier/hostname shorthand
        client_type: Client type without version (e.g., "radarr", "sonarr", "magazarr")
        download_category: Optional download category override
            (e.g., "movies", "tv", "docs")

    Returns:
        Deterministic package ID in format: Quasarr_{download_category}_{hash32}
    """
    # Normalize inputs for consistency
    normalized_title = title.strip()
    normalized_source = source_key.lower().strip() if source_key else "unknown"
    normalized_client = client_type.lower().strip() if client_type else "unknown"

    # Determine download category
    if download_category and download_category_exists(download_category):
        final_download_category = download_category
    else:
        # Fallback to client type mapping
        final_download_category = CLIENT_DOWNLOAD_CATEGORY_FALLBACK_MAP.get(
            normalized_client, "tv"
        )

    # Create deterministic hash from combination using SHA256
    hash_input = f"{normalized_title}|{normalized_source}|{normalized_client}"
    hash_bytes = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    # Use first 32 characters for good collision resistance (128-bit)
    return f"Quasarr_{final_download_category}_{hash_bytes[:32]}"


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


def classify_links(links):
    """
    Classify links into direct/auto/protected categories.
    Direct = anything that's not a known crypter or junkies link.
    Mirror names from source are preserved.
    """
    classified = {"direct": [], "auto": [], "protected": []}

    for link in links:
        url = link[0]
        mirror = link[1] if len(link) > 1 else ""

        if isinstance(mirror, str) and mirror.lower() == "junkies":
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


def _persist_failed_package(
    shared_state, title, package_id, reason, remove_protected=False
):
    if remove_protected:
        try:
            shared_state.get_db("protected").delete(package_id)
        except Exception as e:
            info(f'Error removing protected package "{package_id}" before fail: {e}')
    fail(title, package_id, shared_state, reason=reason)
    return {"success": False, "persisted_failure": True, "reason": reason}


def _get_protected_release(shared_state, package_id):
    try:
        raw_data = shared_state.get_db("protected").retrieve(package_id)
        data = json.loads(raw_data) if raw_data else None
    except Exception as e:
        info(f'Error reading protected package "{package_id}" for notification: {e}')
        return None
    return data if isinstance(data, dict) else None


def _delete_protected_package(shared_state, package_id):
    try:
        shared_state.get_db("protected").delete(package_id)
    except Exception as e:
        info(f'Error removing protected package "{package_id}": {e}')


def _format_mirror_token_list(tokens):
    cleaned = [str(token) for token in sorted(tokens) if token]
    return ", ".join(cleaned) if cleaned else "unknown"


def submit_final_download_urls(
    shared_state,
    urls,
    title,
    password,
    package_id,
    remove_protected=False,
    notification_details=None,
):
    """
    Final mirror whitelist check before sending direct HTTP links to JDownloader.
    """
    protected_release = None
    if remove_protected:
        protected_release = _get_protected_release(shared_state, package_id) or {
            "title": title
        }
    category = get_download_category_from_package_id(package_id)
    mirrors = get_download_category_mirrors(category, lowercase=True)
    filtered = filter_final_download_urls(urls, mirrors)
    final_urls = filtered["urls"]
    dropped = filtered["dropped"]

    if mirrors and dropped:
        info(
            f"Final mirror-whitelist check kept <g>{len(final_urls)}</g> of <y>{len(urls)}</y> links "
            f'for "{title}" in category "{category}" '
            f"(allowed: {_format_mirror_token_list(filtered['allowed_tokens'])}, "
            f"dropped: {_format_mirror_token_list({item['token'] for item in dropped})})"
        )

    if mirrors and not final_urls:
        reason = (
            f'All final download links were rejected by the mirror-whitelist for category "{category}". '
            f"Allowed mirrors: {_format_mirror_token_list(filtered['allowed_tokens'])}. "
            f"Received mirrors: {_format_mirror_token_list({item['token'] for item in dropped})}."
        )
        result = _persist_failed_package(
            shared_state,
            title,
            package_id,
            reason,
            remove_protected=remove_protected,
        )
        if protected_release:
            update_release_notification(
                shared_state,
                protected_release,
                NotificationType.FAILED,
                details={"reason": reason},
            )
        return result

    info(f"Sending {len(final_urls)} direct download links for {title}")
    if download_package(final_urls, title, password, package_id, shared_state):
        if remove_protected:
            _delete_protected_package(shared_state, package_id)
            if protected_release:
                update_release_notification(
                    shared_state,
                    protected_release,
                    NotificationType.SOLVED,
                    details=notification_details,
                )
        return {"success": True, "links": final_urls}
    return {
        "success": False,
        "reason": f"Failed to add {len(final_urls)} links to linkgrabber",
    }


def handle_direct_links(shared_state, links, title, password, package_id):
    """Send direct hoster links to JDownloader."""
    urls = [link[0] for link in links]
    result = submit_final_download_urls(shared_state, urls, title, password, package_id)
    if result["success"]:
        StatsHelper(shared_state).increment_package_with_links(result["links"])
        return {"success": True}
    return result


def handle_auto_decrypt_links(shared_state, links, title, password, package_id):
    """Decrypt hide.cx links and send to JDownloader."""
    result = decrypt_links_if_hide(shared_state, links)

    if result.get("status") != "success":
        return {"success": False, "reason": "Auto-decrypt failed"}

    decrypted_urls = result.get("results", [])
    if not decrypted_urls:
        return {"success": False, "reason": "No links decrypted"}

    info(f"Decrypted <g>{len(decrypted_urls)}</g> download links for {title}")

    submit_result = submit_final_download_urls(
        shared_state, decrypted_urls, title, password, package_id
    )
    if submit_result["success"]:
        StatsHelper(shared_state).increment_package_with_links(submit_result["links"])
        return {"success": True}
    return submit_result


def store_protected_links(
    shared_state,
    links,
    title,
    password,
    package_id,
    size_mb=None,
    original_url=None,
    imdb_id=None,
    notifications=None,
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
    if imdb_id:
        blob_data["imdb_id"] = imdb_id
    if notifications:
        blob_data["notifications"] = notifications

    shared_state.values["database"]("protected").update_store(
        package_id, json.dumps(blob_data)
    )
    info(
        f'CAPTCHA-Solution required for <b>{title}</b> at: "{shared_state.values["external_address"]}/captcha"'
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
    title = normalize_download_title(source_result.get("title") or title)

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

    classified = classify_links(links)

    # PRIORITY 1: Direct hoster links
    if classified["direct"]:
        info(
            f"Found <g>{len(classified['direct'])}</g> direct hoster links for {title}"
        )
        result = handle_direct_links(
            shared_state, classified["direct"], title, password, package_id
        )
        if result["success"]:
            send_notification(
                shared_state,
                title=title,
                case=NotificationType.UNPROTECTED,
                imdb_id=imdb_id,
                source=source_url,
            )
            return {"success": True, "title": title}
        if result.get("persisted_failure"):
            return {"success": True, "title": title, "failed": True}
        return fail(title, package_id, shared_state, reason=result.get("reason"))

    # PRIORITY 2: Auto-decryptable (hide.cx)
    if classified["auto"]:
        info(
            f"Found <g>{len(classified['auto'])}</g> auto-decryptable links for {title}"
        )
        result = handle_auto_decrypt_links(
            shared_state, classified["auto"], title, password, package_id
        )
        if result["success"]:
            send_notification(
                shared_state,
                title=title,
                case=NotificationType.UNPROTECTED,
                imdb_id=imdb_id,
                source=source_url,
            )
            return {"success": True, "title": title}
        if result.get("persisted_failure"):
            return {"success": True, "title": title, "failed": True}
        info(f"Auto-decrypt failed for {title}, falling back to manual CAPTCHA...")
        classified["protected"].extend(classified["auto"])

    # PRIORITY 3: Protected (filecrypt, tolink, keeplinks, junkies)
    if classified["protected"]:
        info(f"Found <g>{len(classified['protected'])}</g> protected links for {title}")
        notification_references = send_tracked_notification(
            shared_state,
            title=title,
            case=NotificationType.CAPTCHA,
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
            imdb_id=imdb_id,
            notifications=notification_references,
        )
        return {"success": True, "title": title}

    return fail(
        title,
        package_id,
        shared_state,
        reason=f'No usable links found for {title} on {label} - "{source_url}"',
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

    data = (
        shared_state.run_device_request(
            "load package state for duplicate detection",
            lambda _device: get_packages(shared_state),
            default={},
        )
        or {}
    )

    for section in ("queue", "history"):
        for pkg in data.get(section, []) or []:
            if pkg.get("nzo_id") == package_id:
                return True

    return False


def download(
    shared_state,
    request_from,
    download_category,
    title,
    url,
    size_mb,
    password,
    imdb_id,
    source_key,
):
    """
    Main download entry point.

    Args:
        shared_state: Application shared state
        request_from: User-Agent string (e.g., "Radarr/6.0.4.10291")
        download_category: Download category (e.g., "movies", "tv", "docs")
        title: Release title
        url: Source URL
        size_mb: Size in MB
        password: Archive password
        imdb_id: IMDb ID (optional)
        source_key: Hostname shorthand from search. If not provided,
                    will be derived from URL matching against configured hostnames.
    """
    package_id = None
    try:
        if imdb_id and imdb_id.lower() == "none":
            imdb_id = None

        title = normalize_download_title(title)
        config = shared_state.values["config"]("Hostnames")

        # Extract client type (without version) for deterministic hashing
        client_type = extract_client_type(request_from)

        # Find matching source - all getters have unified signature
        source_result = None
        label = None
        detected_source_key = None

        mirrors = get_download_category_mirrors(download_category, lowercase=True)
        download_sources = get_download_sources()

        normalized_source_key = None
        if source_key and isinstance(source_key, str):
            normalized_source_key = source_key.lower().strip()

        source_candidates = []
        if normalized_source_key and normalized_source_key in download_sources:
            source_candidates.append(
                (normalized_source_key, download_sources[normalized_source_key], True)
            )

        for key, source in download_sources.items():
            if normalized_source_key and key == normalized_source_key:
                continue
            source_candidates.append((key, source, False))

        for key, source, from_source_key in source_candidates:
            hostname = config.get(key)
            if not from_source_key and not (
                hostname and hostname.lower() in url.lower()
            ):
                continue

            try:
                # Mirrors are download-category-driven and passed to each source getter.
                candidate_result = source.get_download_links(
                    shared_state, url, mirrors, title, password
                )
                if candidate_result and candidate_result.get("links"):
                    clear_hostname_issue(key)
                    source_result = candidate_result
                    label = key.upper()
                    detected_source_key = key
                    break
            except Exception as e:
                info(f"Error getting download links from {key.upper()}: {e}")
                if not from_source_key or (
                    hostname and hostname.lower() in url.lower()
                ):
                    mark_hostname_issue(key, "download", str(e))

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
        package_id = generate_deterministic_package_id(
            title, final_source_key, client_type, download_category
        )

        # Skip Download if package_id already exists
        if package_id_exists(shared_state, package_id):
            warn(f"Package {package_id} already exists. Skipping download!")
            return {"success": True, "package_id": package_id, "title": title}

        if source_result is None:
            result = fail(
                title,
                package_id,
                shared_state,
                reason=f'Could not find matching source for "{title}" - "{url}"',
            )
            return {"package_id": package_id, **result}

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

    except Exception as e:
        if not package_id:
            # Fallback generation if we crashed early
            try:
                client_type = extract_client_type(request_from)
            except Exception:
                client_type = "unknown"

            final_source_key = source_key if source_key else "unknown"

            package_id = generate_deterministic_package_id(
                title, final_source_key, client_type, download_category
            )

        result = fail(title, package_id, shared_state, reason=f"Unexpected error: {e}")
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
    return {"success": True, "title": title, "failed": True}
