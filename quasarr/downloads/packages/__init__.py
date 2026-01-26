# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import traceback
from collections import defaultdict
from urllib.parse import urlparse

from quasarr.providers.jd_cache import JDPackageCache
from quasarr.providers.log import debug, info

# =============================================================================
# CONSTANTS
# =============================================================================

PACKAGE_ID_PREFIX = "Quasarr_"

# Categories used for package classification
CATEGORY_MOVIES = "movies"
CATEGORY_TV = "tv"
CATEGORY_DOCS = "docs"
CATEGORY_NOT_QUASARR = "not_quasarr"

# Known archive extensions for file detection
ARCHIVE_EXTENSIONS = frozenset(
    [
        ".rar",
        ".zip",
        ".7z",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".001",
        ".002",
        ".003",
        ".004",
        ".005",
        ".006",
        ".007",
        ".008",
        ".009",
        ".r00",
        ".r01",
        ".r02",
        ".r03",
        ".r04",
        ".r05",
        ".r06",
        ".r07",
        ".r08",
        ".r09",
        ".part1.rar",
        ".part01.rar",
        ".part001.rar",
        ".part2.rar",
        ".part02.rar",
        ".part002.rar",
    ]
)

# JDownloader extraction complete status markers (checked case-insensitively)
# Add new languages here as needed
EXTRACTION_COMPLETE_MARKERS = (
    "extraction ok",  # English
    "entpacken ok",  # German
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_extraction_complete(status):
    """Check if a JDownloader status string indicates extraction is complete (case-insensitive)."""
    if not status:
        return False
    status_lower = status.lower()
    return any(marker in status_lower for marker in EXTRACTION_COMPLETE_MARKERS)


def is_archive_file(filename, extraction_status=""):
    """Check if a file is an archive based on extension or extraction status."""
    if extraction_status:
        return True
    if not filename:
        return False
    filename_lower = filename.lower()
    return any(filename_lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def get_category_from_package_id(package_id):
    """Extract category from a Quasarr package ID."""
    if not package_id:
        return CATEGORY_NOT_QUASARR
    if CATEGORY_MOVIES in package_id:
        return CATEGORY_MOVIES
    elif CATEGORY_DOCS in package_id:
        return CATEGORY_DOCS
    elif PACKAGE_ID_PREFIX in package_id:
        return CATEGORY_TV
    else:
        return CATEGORY_NOT_QUASARR


def is_quasarr_package(package_id):
    """Check if a package ID belongs to Quasarr."""
    return bool(package_id) and package_id.startswith(PACKAGE_ID_PREFIX)


def get_links_comment(package, package_links):
    """Get comment from the first link matching the package UUID."""
    package_uuid = package.get("uuid")
    if package_uuid and package_links:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                comment = link.get("comment")
                if comment:
                    debug(
                        f"get_links_comment: Found comment '{comment}' for package {package_uuid}"
                    )
                return comment
    return None


def get_links_status(package, all_links, is_archive=False):
    """
    Determine the status of links in a package.

    Returns dict with:
        - all_finished: bool - True if all links are done (download + extraction if applicable)
        - eta: int or None - estimated time remaining
        - error: str or None - error message if any
        - offline_mirror_linkids: list - link UUIDs that are offline but have online mirrors
    """
    package_uuid = package.get("uuid")
    package_name = package.get("name", "unknown")
    debug(
        f"get_links_status: Checking package '{package_name}' ({package_uuid}), is_archive={is_archive}"
    )

    links_in_package = []
    if package_uuid and all_links:
        for link in all_links:
            if link.get("packageUUID") == package_uuid:
                links_in_package.append(link)

    debug(f"get_links_status: Found {len(links_in_package)} links in package")

    all_finished = True
    eta = None
    error = None

    # SAFETY: Track if ANY link has extraction activity - this overrides is_archive=False
    # Catches cases where archive detection failed but extraction is clearly happening
    has_extraction_activity = False

    # Group links by mirror domain
    mirrors = defaultdict(list)
    for link in links_in_package:
        url = link.get("url", "")
        base_domain = urlparse(url).netloc
        mirrors[base_domain].append(link)

    # Check if any mirror has all links online
    has_mirror_all_online = False
    for domain, mirror_links in mirrors.items():
        if all(
            link.get("availability", "").lower() == "online" for link in mirror_links
        ):
            has_mirror_all_online = True
            debug(
                f"get_links_status: Mirror '{domain}' has all {len(mirror_links)} links online"
            )
            break

    # Collect offline link IDs (only if there's an online mirror available)
    offline_links = [
        link
        for link in links_in_package
        if link.get("availability", "").lower() == "offline"
    ]
    offline_ids = [link.get("uuid") for link in offline_links]
    offline_mirror_linkids = offline_ids if has_mirror_all_online else []

    if offline_links:
        debug(
            f"get_links_status: {len(offline_links)} offline links, has_mirror_all_online={has_mirror_all_online}"
        )

    # First pass: detect if ANY link has extraction activity (for safety override)
    for link in links_in_package:
        if link.get("extractionStatus", ""):
            has_extraction_activity = True
            break

    if has_extraction_activity:
        debug(f"get_links_status: Package has extraction activity detected")

    # Second pass: check each link's status
    for link in links_in_package:
        link_name = link.get("name", "unknown")
        link_finished = link.get("finished", False)
        link_availability = link.get("availability", "").lower()
        link_extraction_status = link.get("extractionStatus", "").lower()
        link_status = link.get("status", "")
        link_status_icon = link.get("statusIconKey", "").lower()
        link_eta = link.get("eta", 0) // 1000 if link.get("eta") else 0

        # Determine if THIS LINK is an archive file
        link_is_archive_file = is_archive_file(link_name, link_extraction_status)

        link_status_preview = (
            link_status[:50] + "..." if len(link_status) > 50 else link_status
        )

        debug(
            f"get_links_status: Link '{link_name}': finished={link_finished}, "
            f"is_archive_file={link_is_archive_file}, availability={link_availability}, "
            f"extractionStatus='{link_extraction_status}', status='{link_status_preview}'"
        )

        # Check for offline links
        if link_availability == "offline" and not has_mirror_all_online:
            error = "Links offline for all mirrors"
            debug(
                f"get_links_status: ERROR - Link offline with no online mirror: {link_name}"
            )

        # Check for file errors
        if link_status_icon == "false":
            error = "File error in package"
            debug(f"get_links_status: ERROR - File error in link: {link_name}")

        # === MAIN LINK STATUS LOGIC ===

        if not link_finished:
            # Download not complete
            all_finished = False
            debug(
                f"get_links_status: Link not finished (download in progress): {link_name}"
            )

        elif link_extraction_status and link_extraction_status != "successful":
            # Extraction is running or errored (applies to archive files only)
            if link_extraction_status == "error":
                error = link.get("status", "Extraction error")
                debug(f"get_links_status: Extraction ERROR on {link_name}: {error}")
            elif link_extraction_status == "running":
                debug(
                    f"get_links_status: Extraction RUNNING on {link_name}, eta={link_eta}s"
                )
                if link_eta > 0:
                    if eta is None or link_eta > eta:
                        eta = link_eta
            else:
                debug(
                    f"get_links_status: Extraction status '{link_extraction_status}' on {link_name}"
                )
            all_finished = False

        elif link_is_archive_file:
            # This specific link IS an archive file - must have "extraction ok"
            if is_extraction_complete(link_status):
                debug(f"get_links_status: Archive link COMPLETE: {link_name}")
            else:
                debug(
                    f"get_links_status: Archive link WAITING for extraction: {link_name}, status='{link_status}'"
                )
                all_finished = False

        elif is_archive or has_extraction_activity:
            # Package is marked as archive but THIS link doesn't look like an archive file
            # (e.g., .mkv in a package with .rar files)
            # These non-archive files are finished when download is complete
            debug(
                f"get_links_status: Non-archive link in archive package COMPLETE: {link_name}"
            )

        else:
            # Non-archive file in non-archive package - finished when downloaded
            debug(f"get_links_status: Non-archive link COMPLETE: {link_name}")

    debug(
        f"get_links_status: RESULT for '{package_name}': all_finished={all_finished}, "
        f"eta={eta}, error={error}, is_archive={is_archive}, has_extraction_activity={has_extraction_activity}"
    )

    return {
        "all_finished": all_finished,
        "eta": eta,
        "error": error,
        "offline_mirror_linkids": offline_mirror_linkids,
    }


def get_links_matching_package_uuid(package, package_links):
    """Get all link UUIDs belonging to a package."""
    package_uuid = package.get("uuid")
    link_ids = []

    if not isinstance(package_links, list):
        debug(
            f"get_links_matching_package_uuid: ERROR - expected list, got {type(package_links).__name__}"
        )
        return link_ids

    if package_uuid:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                link_ids.append(link.get("uuid"))
        debug(
            f"get_links_matching_package_uuid: Found {len(link_ids)} links for package {package_uuid}"
        )
    else:
        info("Error - package uuid missing in delete request!")
    return link_ids


def format_eta(seconds):
    """Format seconds as HH:MM:SS."""
    if seconds is None or seconds < 0:
        return "23:59:59"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:02}"


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================


def get_packages(shared_state, _cache=None):
    """
    Get all packages from protected DB, failed DB, linkgrabber, and downloader.

    Args:
        shared_state: The shared state object
        _cache: INTERNAL USE ONLY. Used by delete_package() to share cached data
                within a single request. External callers should never pass this.
    """
    debug("get_packages: Starting package retrieval")
    packages = []

    # Create cache for this request - only valid for duration of this call
    if _cache is None:
        cache = JDPackageCache(shared_state.get_device())
        debug("get_packages: Created new JDPackageCache")
    else:
        cache = _cache
        debug("get_packages: Using provided cache instance")

    # === PROTECTED PACKAGES (CAPTCHA required) ===
    protected_packages = shared_state.get_db("protected").retrieve_all_titles()
    debug(
        f"get_packages: Found {len(protected_packages) if protected_packages else 0} protected packages"
    )

    if protected_packages:
        for package in protected_packages:
            package_id = package[0]
            try:
                data = json.loads(package[1])
                details = {
                    "title": data["title"],
                    "urls": data["links"],
                    "size_mb": data.get("size_mb"),
                    "password": data.get("password"),
                }
                packages.append(
                    {
                        "details": details,
                        "location": "queue",
                        "type": "protected",
                        "package_id": package_id,
                    }
                )
                debug(
                    f"get_packages: Added protected package '{data['title']}' ({package_id})"
                )
            except (json.JSONDecodeError, KeyError) as e:
                debug(
                    f"get_packages: Failed to parse protected package {package_id}: {e}"
                )

    # === FAILED PACKAGES ===
    failed_packages = shared_state.get_db("failed").retrieve_all_titles()
    debug(
        f"get_packages: Found {len(failed_packages) if failed_packages else 0} failed packages"
    )

    if failed_packages:
        for package in failed_packages:
            package_id = package[0]
            try:
                data = json.loads(package[1])
                # Handle double-encoded JSON
                if isinstance(data, str):
                    data = json.loads(data)

                details = {
                    "name": data.get("title", "Unknown"),
                    "bytesLoaded": 0,
                    "saveTo": "/",
                }
                error = data.get("error", "Unknown error")

                packages.append(
                    {
                        "details": details,
                        "location": "history",
                        "type": "failed",
                        "error": error,
                        "comment": package_id,
                        "uuid": package_id,
                    }
                )
                debug(
                    f"get_packages: Added failed package '{details['name']}' ({package_id}): {error}"
                )
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                debug(f"get_packages: Failed to parse failed package {package_id}: {e}")

    # === LINKGRABBER PACKAGES ===
    linkgrabber_packages = cache.linkgrabber_packages
    linkgrabber_links = cache.linkgrabber_links

    debug(f"get_packages: Processing {len(linkgrabber_packages)} linkgrabber packages")

    if linkgrabber_packages:
        for package in linkgrabber_packages:
            package_name = package.get("name", "unknown")
            package_uuid = package.get("uuid")

            comment = get_links_comment(package, linkgrabber_links)
            link_details = get_links_status(
                package, linkgrabber_links, is_archive=False
            )

            error = link_details["error"]
            offline_mirror_linkids = link_details["offline_mirror_linkids"]

            # Clean up offline links if we have online mirrors
            if offline_mirror_linkids:
                debug(
                    f"get_packages: Cleaning up {len(offline_mirror_linkids)} offline links from '{package_name}'"
                )
                try:
                    shared_state.get_device().linkgrabber.cleanup(
                        "DELETE_OFFLINE",
                        "REMOVE_LINKS_ONLY",
                        "SELECTED",
                        offline_mirror_linkids,
                        [package_uuid],
                    )
                except Exception as e:
                    debug(f"get_packages: Failed to cleanup offline links: {e}")

            location = "history" if error else "queue"
            packages.append(
                {
                    "details": package,
                    "location": location,
                    "type": "linkgrabber",
                    "comment": comment,
                    "uuid": package_uuid,
                    "error": error,
                }
            )
            debug(
                f"get_packages: Added linkgrabber package '{package_name}' -> {location}"
            )

    # === DOWNLOADER PACKAGES ===
    downloader_packages = cache.downloader_packages
    downloader_links = cache.downloader_links

    debug(
        f"get_packages: Processing {len(downloader_packages)} downloader packages with {len(downloader_links)} links"
    )

    if downloader_packages and downloader_links:
        # ONE bulk API call for all archive detection, with safety fallbacks
        archive_package_uuids = cache.detect_all_archives(
            downloader_packages, downloader_links
        )
        debug(
            f"get_packages: Archive detection complete - {len(archive_package_uuids)} packages are archives"
        )

        for package in downloader_packages:
            package_name = package.get("name", "unknown")
            package_uuid = package.get("uuid")

            comment = get_links_comment(package, downloader_links)

            # Lookup from cache (populated by detect_all_archives above)
            is_archive = (
                package_uuid in archive_package_uuids if package_uuid else False
            )
            debug(f"get_packages: Package '{package_name}' is_archive={is_archive}")

            link_details = get_links_status(package, downloader_links, is_archive)

            error = link_details["error"]
            finished = link_details["all_finished"]

            # Additional check: if download is 100% complete and no ETA, it's finished
            # This catches non-archive packages or when archive detection fails
            if not finished and not error:
                bytes_total = int(package.get("bytesTotal", 0))
                bytes_loaded = int(package.get("bytesLoaded", 0))
                pkg_eta = package.get("eta")

                # If download is complete and no ETA (paused/finished state)
                if bytes_total > 0 and bytes_loaded >= bytes_total and pkg_eta is None:
                    # Only mark as finished if it's not an archive
                    if not is_archive:
                        debug(
                            f"get_packages: Package '{package_name}' bytes complete and not archive -> marking finished"
                        )
                        finished = True
                    else:
                        debug(
                            f"get_packages: Package '{package_name}' bytes complete BUT is_archive=True -> NOT marking finished yet"
                        )

            if not finished and link_details["eta"]:
                package["eta"] = link_details["eta"]

            location = "history" if error or finished else "queue"

            debug(
                f"get_packages: Package '{package_name}' -> location={location}, "
                f"finished={finished}, error={error}, is_archive={is_archive}"
            )

            packages.append(
                {
                    "details": package,
                    "location": location,
                    "type": "downloader",
                    "comment": comment,
                    "uuid": package_uuid,
                    "error": error,
                    "is_archive": is_archive,
                    "extraction_ok": finished and is_archive,
                }
            )

    # === BUILD RESPONSE ===
    downloads = {"queue": [], "history": []}

    queue_index = 0
    history_index = 0

    for package in packages:
        package_id = None

        if package["location"] == "queue":
            time_left = "23:59:59"
            storage = ""

            if package["type"] == "linkgrabber":
                details = package["details"]
                name = f"[Linkgrabber] {details.get('name', 'unknown')}"
                storage = details.get("saveTo", "")
                try:
                    bytes_total = int(details.get("bytesTotal", 0))
                    mb = mb_left = bytes_total / (1024 * 1024)
                except (KeyError, TypeError, ValueError):
                    bytes_total = 0
                    mb = mb_left = 0
                package_id = package["comment"]
                category = get_category_from_package_id(package_id)
                package_type = "linkgrabber"
                package_uuid = package["uuid"]

            elif package["type"] == "downloader":
                details = package["details"]
                status = "Downloading"
                storage = details.get("saveTo", "")
                pkg_eta = details.get("eta")
                bytes_total = int(details.get("bytesTotal", 0))
                bytes_loaded = int(details.get("bytesLoaded", 0))

                mb = bytes_total / (1024 * 1024)
                mb_left = (
                    (bytes_total - bytes_loaded) / (1024 * 1024) if bytes_total else 0
                )
                if mb_left < 0:
                    mb_left = 0

                if pkg_eta is None:
                    status = "Paused"
                else:
                    time_left = format_eta(int(pkg_eta))
                    if mb_left == 0:
                        status = "Extracting"

                name = f"[{status}] {details.get('name', 'unknown')}"
                package_id = package["comment"]
                category = get_category_from_package_id(package_id)
                package_type = "downloader"
                package_uuid = package["uuid"]

            else:  # protected
                details = package["details"]
                name = f"[CAPTCHA not solved!] {details.get('title', 'unknown')}"
                mb = mb_left = details.get("size_mb") or 0
                bytes_total = 0  # Protected packages don't have reliable byte data
                package_id = package.get("package_id")
                category = get_category_from_package_id(package_id)
                package_type = "protected"
                package_uuid = None

            # Use package_id if available, otherwise use uuid as fallback for non-Quasarr packages
            effective_id = package_id or package_uuid

            if effective_id:
                try:
                    percentage = int(100 * (mb - mb_left) / mb) if mb > 0 else 0
                except (ZeroDivisionError, ValueError, TypeError):
                    percentage = 0

                downloads["queue"].append(
                    {
                        "index": queue_index,
                        "nzo_id": effective_id,
                        "priority": "Normal",
                        "filename": name,
                        "cat": category,
                        "mbleft": int(mb_left) if mb_left else 0,
                        "mb": int(mb) if mb else 0,
                        "bytes": bytes_total,
                        "status": "Downloading",
                        "percentage": percentage,
                        "timeleft": time_left,
                        "type": package_type,
                        "uuid": package_uuid,
                        "is_archive": package.get("is_archive", False),
                        "storage": storage,
                    }
                )
                queue_index += 1
            else:
                debug(
                    f"get_packages: Skipping queue package without package_id or uuid: {name}"
                )

        elif package["location"] == "history":
            details = package["details"]
            name = details.get("name", "unknown")
            try:
                # Use bytesLoaded first, fall back to bytesTotal for failed/incomplete downloads
                size = int(details.get("bytesLoaded", 0)) or int(
                    details.get("bytesTotal", 0)
                )
            except (KeyError, TypeError, ValueError):
                size = 0
            storage = details.get("saveTo", "/")

            package_id = package.get("comment")
            # Use package_id if available, otherwise use uuid as fallback for non-Quasarr packages
            effective_id = package_id or package.get("uuid")
            category = get_category_from_package_id(package_id)

            error = package.get("error")
            fail_message = ""
            if error:
                status = "Failed"
                fail_message = str(error)
            else:
                status = "Completed"

            downloads["history"].append(
                {
                    "fail_message": fail_message,
                    "category": category,
                    "storage": storage,
                    "status": status,
                    "nzo_id": effective_id,
                    "name": name,
                    "bytes": int(size),
                    "percentage": 100,
                    "type": "downloader",
                    "uuid": package.get("uuid"),
                    "is_archive": package.get("is_archive", False),
                    "extraction_ok": package.get("extraction_ok", False),
                    "extraction_status": "SUCCESSFUL"
                    if package.get("extraction_ok", False)
                    else "RUNNING"
                    if package.get("is_archive", False)
                    else "",
                }
            )
            history_index += 1
        else:
            info(f"Invalid package location {package['location']}")

    # === AUTO-START QUASARR PACKAGES ===
    if not cache.is_collecting:
        debug(
            "get_packages: Linkgrabber not collecting, checking for packages to auto-start"
        )

        packages_to_start = []
        links_to_start = []

        for package in linkgrabber_packages:
            comment = get_links_comment(package, linkgrabber_links)
            if is_quasarr_package(comment):
                package_uuid = package.get("uuid")
                if package_uuid:
                    package_link_ids = [
                        link.get("uuid")
                        for link in linkgrabber_links
                        if link.get("packageUUID") == package_uuid and link.get("uuid")
                    ]
                    if package_link_ids:
                        debug(
                            f"get_packages: Found Quasarr package to start: {package.get('name')} with {len(package_link_ids)} links"
                        )
                        packages_to_start.append(package_uuid)
                        links_to_start.extend(package_link_ids)
                    else:
                        info(
                            f"Package {package_uuid} has no links in linkgrabber - skipping start"
                        )
                    # Only start one package at a time
                    break

        if packages_to_start and links_to_start:
            debug(
                f"get_packages: Moving {len(packages_to_start)} packages with {len(links_to_start)} links to download list"
            )
            try:
                shared_state.get_device().linkgrabber.move_to_downloadlist(
                    links_to_start, packages_to_start
                )
                info(
                    f"Started {len(packages_to_start)} package download{'s' if len(packages_to_start) > 1 else ''} from linkgrabber"
                )
            except Exception as e:
                debug(f"get_packages: Failed to move packages to download list: {e}")
    else:
        debug("get_packages: Linkgrabber is collecting, skipping auto-start")

    debug(
        f"get_packages: COMPLETE - queue={len(downloads['queue'])}, history={len(downloads['history'])}"
    )

    # Summary overview for quick debugging
    if downloads["queue"] or downloads["history"]:
        debug("=" * 60)
        debug("PACKAGE SUMMARY")
        debug("=" * 60)
        debug(f"  CACHE: {cache.get_stats()}")
        debug("-" * 60)
        for item in downloads["queue"]:
            is_archive = item.get("is_archive", False)
            archive_indicator = "[ARCHIVE]" if is_archive else ""
            mb = item.get("mb", 0)
            size_str = f"{mb:.0f} MB" if mb < 1024 else f"{mb / 1024:.1f} GB"
            debug(
                f"  QUEUE: {item['filename'][:50]}{'...' if len(item['filename']) > 50 else ''}"
            )
            debug(
                f"         -> {item['percentage']}% | {item['timeleft']} | {size_str} | {item['cat']} {archive_indicator}"
            )
        for item in downloads["history"]:
            status_icon = "✅" if item["status"] == "Completed" else "✗"
            is_archive = item.get("is_archive")
            extraction_ok = item.get("extraction_ok", False)
            # Only show archive status if we know it's an archive
            if is_archive:
                archive_status = (
                    f"[ARCHIVE: {'EXTRACTED ✅' if extraction_ok else 'NOT EXTRACTED'}]"
                )
            else:
                archive_status = ""
            # Format size
            size_bytes = item.get("bytes", 0)
            if size_bytes > 0:
                size_mb = size_bytes / (1024 * 1024)
                size_str = (
                    f"{size_mb:.0f} MB"
                    if size_mb < 1024
                    else f"{size_mb / 1024:.1f} GB"
                )
            else:
                size_str = "? MB"
            debug(
                f"  HISTORY: {item['name'][:50]}{'...' if len(item['name']) > 50 else ''}"
            )
            debug(
                f"           -> {status_icon} {item['status']} | {size_str} | {item['category']} {archive_status}"
            )
            if item.get("fail_message"):
                debug(f"              Error: {item['fail_message']}")
        debug("=" * 60)

    return downloads


def delete_package(shared_state, package_id):
    """Delete a package from JDownloader and/or the database."""
    debug(f"delete_package: Starting deletion of package {package_id}")

    try:
        deleted_title = ""

        # Create cache for this single delete operation
        # Safe to reuse within this request since we fetch->find->delete atomically
        cache = JDPackageCache(shared_state.get_device())

        packages = get_packages(shared_state, _cache=cache)

        found = False
        for package_location in packages:
            for package in packages[package_location]:
                # Compare as strings to handle int UUIDs from JDownloader
                if str(package.get("nzo_id", "")) == str(package_id):
                    found = True
                    package_type = package.get("type")
                    package_uuid = package.get("uuid")

                    debug(
                        f"delete_package: Found package to delete - type={package_type}, uuid={package_uuid}, location={package_location}"
                    )

                    # Clean up JDownloader links if applicable
                    if package_type == "linkgrabber":
                        ids = get_links_matching_package_uuid(
                            package, cache.linkgrabber_links
                        )
                        if ids:
                            debug(
                                f"delete_package: Deleting {len(ids)} links from linkgrabber"
                            )
                            try:
                                shared_state.get_device().linkgrabber.cleanup(
                                    "DELETE_ALL",
                                    "REMOVE_LINKS_AND_DELETE_FILES",
                                    "SELECTED",
                                    ids,
                                    [package_uuid],
                                )
                            except Exception as e:
                                debug(
                                    f"delete_package: Linkgrabber cleanup failed: {e}"
                                )
                        else:
                            debug(
                                f"delete_package: No link IDs found for linkgrabber package"
                            )

                    elif package_type == "downloader":
                        ids = get_links_matching_package_uuid(
                            package, cache.downloader_links
                        )
                        if ids:
                            debug(
                                f"delete_package: Deleting {len(ids)} links from downloader"
                            )
                            try:
                                shared_state.get_device().downloads.cleanup(
                                    "DELETE_ALL",
                                    "REMOVE_LINKS_AND_DELETE_FILES",
                                    "SELECTED",
                                    ids,
                                    [package_uuid],
                                )
                            except Exception as e:
                                debug(f"delete_package: Downloads cleanup failed: {e}")
                        else:
                            debug(
                                f"delete_package: No link IDs found for downloader package"
                            )

                    # Always clean up database entries (no state check - just clean whatever exists)
                    debug(
                        f"delete_package: Cleaning up database entries for {package_id}"
                    )
                    try:
                        shared_state.get_db("failed").delete(package_id)
                        debug(
                            f"delete_package: Deleted from failed DB (or was not present)"
                        )
                    except Exception as e:
                        debug(
                            f"delete_package: Failed DB delete exception (may be normal): {e}"
                        )
                    try:
                        shared_state.get_db("protected").delete(package_id)
                        debug(
                            f"delete_package: Deleted from protected DB (or was not present)"
                        )
                    except Exception as e:
                        debug(
                            f"delete_package: Protected DB delete exception (may be normal): {e}"
                        )

                    # Get title for logging
                    if package_location == "queue":
                        deleted_title = package.get("filename", "")
                    else:
                        deleted_title = package.get("name", "")

                    break  # Exit inner loop - we found and processed the package

            if found:
                break  # Exit outer loop

        if deleted_title:
            info(f'Deleted package "{deleted_title}" with ID "{package_id}"')
        else:
            info(f'Deleted package "{package_id}"')

        debug(
            f"delete_package: Successfully completed deletion for package {package_id}, found={found}"
        )
        return True

    except Exception as e:
        info(f"Failed to delete package {package_id}")
        debug(f"delete_package: Exception during deletion: {type(e).__name__}: {e}")
        debug(f"delete_package: Traceback: {traceback.format_exc()}")
        return False
