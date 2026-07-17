# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import time
import traceback
from collections import defaultdict
from urllib.parse import urlparse

from quasarr.constants import (
    ARCHIVE_EXTENSIONS,
    EXTRACTION_COMPLETE_MARKERS,
    NOT_DOWNLOADABLE_MARKERS,
    PACKAGE_ID_PATTERN,
)
from quasarr.downloads.episode_links import trim_to_requested_episodes
from quasarr.providers.jd_cache import JDPackageCache
from quasarr.providers.log import debug, info, trace
from quasarr.storage.categories import get_download_category_from_package_id

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_extraction_complete(status):
    """Check if a JDownloader status string indicates extraction is complete (case-insensitive)."""
    if not status:
        return False
    status_lower = status.lower()
    return any(marker in status_lower for marker in EXTRACTION_COMPLETE_MARKERS)


def is_not_downloadable(status):
    """Check if a JDownloader status string marks a link as not downloadable (case-insensitive)."""
    if not status:
        return False
    status_lower = status.lower()
    return any(marker in status_lower for marker in NOT_DOWNLOADABLE_MARKERS)


def is_archive_file(filename, extraction_status=""):
    """Check if a file is an archive based on extension or extraction status."""
    if extraction_status:
        return True
    if not filename:
        return False
    filename_lower = filename.lower()
    return any(filename_lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def is_quasarr_package(package_id):
    """Check if a package ID belongs to Quasarr using strict pattern matching."""
    if not package_id:
        return False
    return bool(PACKAGE_ID_PATTERN.match(str(package_id)))


def get_links_comment(package, package_links):
    """Get the first non-empty comment from links matching the package UUID."""
    package_uuid = package.get("uuid")
    fallback_comment = None
    if package_uuid and package_links:
        for link in package_links:
            if link.get("packageUUID") != package_uuid:
                continue
            comment = link.get("comment")
            if not comment:
                continue
            if is_quasarr_package(comment):
                trace(f"Found comment '{comment}' for package {package_uuid}")
                return comment
            if fallback_comment is None:
                fallback_comment = comment
    if fallback_comment:
        trace(
            f"Using non-Quasarr fallback comment '{fallback_comment}' for package {package_uuid}"
        )
        return fallback_comment
    return None


def get_links_status(package, all_links, is_archive=False):
    """
    Determine the status of links in a package.

    Returns dict with:
        - all_finished: bool - True if all links are done (download + extraction if applicable)
        - eta: int or None - estimated time remaining
        - error: str or None - error message if any
        - offline_mirror_linkids: list - offline link UUIDs to clean up (online mirror exists)
        - not_downloadable_linkids: list - "not downloadable" link UUIDs to remove by id (online mirror exists)
        - file_error_linkids: list - file-error (statusIconKey "false") link UUIDs to remove by id (online mirror exists)
    """
    package_uuid = package.get("uuid")
    package_name = package.get("name", "unknown")
    trace(
        f"Checking package '{package_name}' ({package_uuid}), is_archive={is_archive}"
    )

    links_in_package = []
    if package_uuid and all_links:
        for link in all_links:
            if link.get("packageUUID") == package_uuid:
                links_in_package.append(link)

    trace(f"Found {len(links_in_package)} links in package")

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

    # Classify the three ways a single link can be unusable while a sibling
    # mirror is fine. They surface through different JD signals depending on the
    # list a link sits in:
    #   - offline       : availability == "offline" (linkgrabber only)
    #   - not-downloadable: status contains "Not downloadable!" (availability stays "online")
    #   - file error    : statusIconKey == "false" (how the download list reports dead links)
    def _is_offline(link):
        return link.get("availability", "").lower() == "offline"

    def _is_file_error(link):
        return str(link.get("statusIconKey", "")).lower() == "false"

    def _is_not_downloadable(link):
        return is_not_downloadable(link.get("status"))

    # A link counts toward a "healthy mirror" only if it is none of the above.
    # JD only reports "availability" in the linkgrabber; download-list links
    # have it empty, so an empty value is treated as online.
    def _link_is_online(link):
        if _is_offline(link) or _is_not_downloadable(link) or _is_file_error(link):
            return False
        return link.get("availability", "").lower() in ("online", "")

    has_mirror_all_online = False
    for domain, mirror_links in mirrors.items():
        if all(_link_is_online(link) for link in mirror_links):
            has_mirror_all_online = True
            debug(f"Mirror '{domain}' has all {len(mirror_links)} links online")
            break

    # Collect link IDs to clean up, but only when a healthy mirror can still
    # finish the package — otherwise the error path marks the release failed.
    # Offline links are removed via JD's DELETE_OFFLINE filter (linkgrabber);
    # not-downloadable and file-error links keep availability "online" / are in
    # the download list, so DELETE_OFFLINE skips them and they are removed by id.
    # The lists are mutually exclusive so an id is never removed twice.
    offline_links = [link for link in links_in_package if _is_offline(link)]
    not_downloadable_links = [
        link
        for link in links_in_package
        if _is_not_downloadable(link) and not _is_offline(link)
    ]
    file_error_links = [
        link
        for link in links_in_package
        if _is_file_error(link)
        and not _is_offline(link)
        and not _is_not_downloadable(link)
    ]

    def _ids(links):
        return [link.get("uuid") for link in links] if has_mirror_all_online else []

    offline_mirror_linkids = _ids(offline_links)
    not_downloadable_linkids = _ids(not_downloadable_links)
    file_error_linkids = _ids(file_error_links)

    if offline_links or not_downloadable_links or file_error_links:
        debug(
            f"{len(offline_links)} offline, {len(not_downloadable_links)} not-downloadable, "
            f"{len(file_error_links)} file-error links, has_mirror_all_online={has_mirror_all_online}"
        )

    # First pass: detect if ANY link has extraction activity (for safety override)
    for link in links_in_package:
        if link.get("extractionStatus", ""):
            has_extraction_activity = True
            break

    if has_extraction_activity:
        debug("Package has extraction activity detected")

    # Second pass: check each link's status
    for link in links_in_package:
        link_name = link.get("name", "unknown")
        link_finished = link.get("finished", False)
        link_availability = link.get("availability", "").lower()
        link_extraction_status = link.get("extractionStatus", "").lower()
        link_status = link.get("status", "")
        link_status_icon = link.get("statusIconKey", "").lower()
        link_eta = link.get("eta", 0) // 1000 if link.get("eta") else 0

        if is_not_downloadable(link_status):
            link_availability = "not downloadable"

        # Determine if THIS LINK is an archive file
        link_is_archive_file = is_archive_file(link_name, link_extraction_status)

        link_status_preview = (
            link_status[:50] + "..." if len(link_status) > 50 else link_status
        )

        trace(
            f"Link '{link_name}': finished={link_finished}, "
            f"is_archive_file={link_is_archive_file}, availability={link_availability}, "
            f"extractionStatus='{link_extraction_status}', status='{link_status_preview}'"
        )

        # Check for offline links
        if (
            link_availability in ["offline", "not downloadable"]
            and not has_mirror_all_online
        ):
            error = f"Links {link_availability} for all mirrors"
            debug(
                f"ERROR - Link {link_availability} with no online mirror: {link_name}"
            )

        # Check for file errors. With a healthy mirror present the bad link is
        # removed below instead of failing the whole package.
        if link_status_icon == "false" and not has_mirror_all_online:
            error = "File error in package"
            debug(f"ERROR - File error in link: {link_name}")

        # === MAIN LINK STATUS LOGIC ===

        if not link_finished:
            # Download not complete
            all_finished = False
            trace(f"Link not finished (download in progress): {link_name}")

        elif link_extraction_status and link_extraction_status != "successful":
            # Extraction is running or errored (applies to archive files only)
            if link_extraction_status == "error":
                error = link.get("status", "Extraction error")
                trace(f"Extraction ERROR on {link_name}: {error}")
            elif link_extraction_status == "running":
                trace(f"Extraction RUNNING on {link_name}, eta={link_eta}s")
                if link_eta > 0:
                    if eta is None or link_eta > eta:
                        eta = link_eta
            else:
                trace(f"Extraction status '{link_extraction_status}' on {link_name}")
            all_finished = False

        elif link_is_archive_file:
            # This specific link IS an archive file - must have "extraction ok"
            if is_extraction_complete(link_status):
                trace(f"Archive link COMPLETE: {link_name}")
            else:
                trace(
                    f"Archive link WAITING for extraction: {link_name}, status='{link_status}'"
                )
                all_finished = False

        elif is_archive or has_extraction_activity:
            # Package is marked as archive but THIS link doesn't look like an archive file
            # (e.g., .mkv in a package with .rar files)
            # These non-archive files are finished when download is complete
            debug(f"Non-archive link in archive package COMPLETE: {link_name}")

        else:
            # Non-archive file in non-archive package - finished when downloaded
            debug(f"Non-archive link COMPLETE: {link_name}")

    trace(
        f"RESULT for '{package_name}': all_finished={all_finished}, "
        f"eta={eta}, error={error}, is_archive={is_archive}, has_extraction_activity={has_extraction_activity}"
    )

    return {
        "all_finished": all_finished,
        "eta": eta,
        "error": error,
        "offline_mirror_linkids": offline_mirror_linkids,
        "not_downloadable_linkids": not_downloadable_linkids,
        "file_error_linkids": file_error_linkids,
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


def get_packages(shared_state, _cache=None, auto_start=True):
    """
    Get all packages from protected DB, failed DB, linkgrabber, and downloader.

    Args:
        shared_state: The shared state object
        _cache: INTERNAL USE ONLY. Used by delete_package() to share cached data
        auto_start: Whether to auto-start Quasarr packages from linkgrabber
                within a single request. External callers should never pass this.
    """
    trace("Starting package retrieval")
    packages = []

    # Create cache for this request - only valid for duration of this call
    if _cache is None:
        cache = JDPackageCache(shared_state.get_device())
        trace("Created new JDPackageCache")
    else:
        cache = _cache
        trace("Using provided cache instance")

    # === PROTECTED PACKAGES (CAPTCHA required) ===
    protected_packages = shared_state.get_db("protected").retrieve_all_titles()
    debug(
        f"Found <g>{len(protected_packages) if protected_packages else 0}</g> protected packages"
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
                trace(f"Protected package: '{data['title']}' ({package_id})")
            except (json.JSONDecodeError, KeyError) as e:
                debug(f"Failed to parse protected package {package_id}: {e}")

    # === FAILED PACKAGES ===
    failed_packages = shared_state.get_db("failed").retrieve_all_titles()
    debug(
        f"Found <g>{len(failed_packages) if failed_packages else 0}</g> failed packages"
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
                trace(f"Failed package: '{details['name']}' ({package_id}): {error}")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                debug(f"Failed to parse failed package {package_id}: {e}")

    # === LINKGRABBER PACKAGES ===
    linkgrabber_packages = cache.linkgrabber_packages
    linkgrabber_links = cache.linkgrabber_links

    debug(f"Processing <g>{len(linkgrabber_packages)}</g> linkgrabber packages")

    if linkgrabber_packages:
        for package in linkgrabber_packages:
            package_name = package.get("name", "unknown")
            package_uuid = package.get("uuid")

            comment = package.get("comment")
            if not is_quasarr_package(comment):
                comment = get_links_comment(package, linkgrabber_links)
            # Validate comment is a real ID - if not, ignore it
            if not is_quasarr_package(comment):
                comment = None

            link_details = get_links_status(
                package, linkgrabber_links, is_archive=False
            )

            error = link_details["error"]
            offline_mirror_linkids = link_details["offline_mirror_linkids"]

            # Clean up offline links if we have online mirrors
            if offline_mirror_linkids:
                debug(
                    f"Cleaning up {len(offline_mirror_linkids)} offline links from '{package_name}'"
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
                    debug(f"Failed to cleanup offline links: {e}")

            # Not-downloadable and file-error links keep availability "online"
            # (or have none), so DELETE_OFFLINE skips them; remove them by id so
            # they cannot stall the package while a healthy mirror exists.
            remove_by_id = (
                link_details["not_downloadable_linkids"]
                + link_details["file_error_linkids"]
            )
            if remove_by_id:
                debug(
                    f"Removing {len(remove_by_id)} unusable links from '{package_name}'"
                )
                try:
                    # package_ids must be empty: passing the package id would
                    # remove the whole package, not just the unusable links.
                    shared_state.get_device().linkgrabber.remove_links(
                        remove_by_id,
                        [],
                    )
                except Exception as e:
                    debug(f"Failed to remove unusable links: {e}")

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
            trace(f"Linkgrabber package: '{package_name}' -> {location}")

    # === DOWNLOADER PACKAGES ===
    downloader_packages = cache.downloader_packages
    downloader_links = cache.downloader_links

    debug(
        f"Processing <g>{len(downloader_packages)}</g> downloader packages with <g>{len(downloader_links)}</g> links"
    )

    if downloader_packages and downloader_links:
        # ONE bulk API call for all archive detection, with safety fallbacks
        archive_package_uuids = cache.detect_all_archives(
            downloader_packages, downloader_links
        )
        debug(
            f"Archive detection complete - {len(archive_package_uuids)} packages are archives"
        )

        for package in downloader_packages:
            package_name = package.get("name", "unknown")
            package_uuid = package.get("uuid")

            comment = package.get("comment")
            if not is_quasarr_package(comment):
                comment = get_links_comment(package, downloader_links)
            # Validate comment is a real ID - if not, ignore it
            if not is_quasarr_package(comment):
                comment = None

            # Lookup from cache (populated by detect_all_archives above)
            is_archive = (
                package_uuid in archive_package_uuids if package_uuid else False
            )
            debug(f"Package '{package_name}' is_archive={is_archive}")

            link_details = get_links_status(package, downloader_links, is_archive)

            error = link_details["error"]
            finished = link_details["all_finished"]

            # Links can go offline, flip to "Not downloadable!", or hit a file
            # error after auto-start, while they sit in the downloader list. The
            # linkgrabber's DELETE_OFFLINE cleanup never runs here, so remove all
            # three kinds by id (when a healthy mirror exists) — otherwise the
            # dead link holds the package at all_finished=false forever.
            removable_linkids = (
                link_details["offline_mirror_linkids"]
                + link_details["not_downloadable_linkids"]
                + link_details["file_error_linkids"]
            )
            if removable_linkids:
                debug(
                    f"Removing {len(removable_linkids)} unusable links from downloader package '{package_name}'"
                )
                try:
                    # package_ids must be empty: passing the package id would
                    # remove the whole package, not just the unusable links.
                    shared_state.get_device().downloads.remove_links(
                        removable_linkids,
                        [],
                    )
                except Exception as e:
                    debug(f"Failed to remove unusable links: {e}")

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
                        trace(
                            f"Package '{package_name}' bytes complete and not archive -> marking finished"
                        )
                        finished = True
                    else:
                        trace(
                            f"Package '{package_name}' bytes complete BUT is_archive=True -> NOT marking finished yet"
                        )

            if not finished and link_details["eta"]:
                package["eta"] = link_details["eta"]

            location = "history" if error or finished else "queue"

            trace(
                f"Package '{package_name}' -> location={location}, "
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
    linkgrabber_collecting = bool(cache.is_collecting)
    downloads = {
        "queue": [],
        "history": [],
        "linkgrabber": {
            "is_collecting": linkgrabber_collecting,
            "is_stopped": not linkgrabber_collecting,
        },
    }

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
                category = get_download_category_from_package_id(package_id)
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
                category = get_download_category_from_package_id(package_id)
                package_type = "downloader"
                package_uuid = package["uuid"]

            else:  # protected
                details = package["details"]
                name = f"[CAPTCHA not solved!] {details.get('title', 'unknown')}"
                mb = mb_left = details.get("size_mb") or 0
                bytes_total = 0  # Protected packages don't have reliable byte data
                package_id = package.get("package_id")
                category = get_download_category_from_package_id(package_id)
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
                        "mbleft": int(float(mb_left)) if mb_left else 0,
                        "mb": int(float(mb)) if mb else 0,
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
                debug(f"Skipping queue package without package_id or uuid: {name}")

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
            category = get_download_category_from_package_id(package_id)

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
                    "type": package.get(
                        "type", "downloader"
                    ),  # FIX: Use original type, default to downloader
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
    if auto_start and not linkgrabber_collecting:
        debug("Linkgrabber not collecting, checking for packages to auto-start")

        packages_to_start = []
        links_to_start = []

        for package in linkgrabber_packages:
            comment = get_links_comment(package, linkgrabber_links)
            if is_quasarr_package(comment):
                package_uuid = package.get("uuid")
                if package_uuid:
                    package_links = [
                        link
                        for link in linkgrabber_links
                        if link.get("packageUUID") == package_uuid
                    ]
                    # A single-episode grab can still carry a whole season's
                    # links. File names are known now, so drop the other
                    # episodes before the package starts; when links were
                    # removed, start on the next pass so JD's state settles.
                    if trim_to_requested_episodes(
                        shared_state, package.get("name"), package_links
                    ):
                        break
                    package_link_ids = [
                        link.get("uuid") for link in package_links if link.get("uuid")
                    ]
                    if package_link_ids:
                        debug(
                            f"Found Quasarr package to start: {package.get('name')} with {len(package_link_ids)} links"
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
                f"Moving <g>{len(packages_to_start)}</g> packages with <g>{len(links_to_start)}</g> links to download list"
            )
            try:
                shared_state.get_device().linkgrabber.move_to_downloadlist(
                    links_to_start, packages_to_start
                )
                debug(
                    f"Started {len(packages_to_start)} package download{'s' if len(packages_to_start) > 1 else ''} from linkgrabber"
                )
            except Exception as e:
                debug(f"Failed to move packages to download list: {e}")
    elif auto_start:
        debug("Linkgrabber is collecting, skipping auto-start")

    trace(
        f"COMPLETE - queue={len(downloads['queue'])}, history={len(downloads['history'])}"
    )

    # Summary overview for quick debugging
    if downloads["queue"] or downloads["history"]:
        trace("=" * 60)
        trace("PACKAGE SUMMARY")
        trace("=" * 60)
        trace(f"  CACHE: {cache.get_stats()}")
        trace("-" * 60)
        for item in downloads["queue"]:
            is_archive = item.get("is_archive", False)
            archive_indicator = "[ARCHIVE]" if is_archive else ""
            mb = item.get("mb", 0)
            size_str = f"{mb:.0f} MB" if mb < 1024 else f"{mb / 1024:.1f} GB"
            trace(
                f"  QUEUE: {item['filename'][:50]}{'...' if len(item['filename']) > 50 else ''}"
            )
            trace(
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
            trace(
                f"  HISTORY: {item['name'][:50]}{'...' if len(item['name']) > 50 else ''}"
            )
            trace(
                f"           -> {status_icon} {item['status']} | {size_str} | {item['category']} {archive_status}"
            )
            if item.get("fail_message"):
                trace(f"              Error: {item['fail_message']}")
        trace("=" * 60)

    return downloads


def delete_package(shared_state, package_id, package_title=None, missing_ok=False):
    """Delete a package from JDownloader and/or the database."""
    debug(
        f"delete_package: Starting deletion of package {package_id} (title: {package_title})"
    )

    try:
        # Create cache for this single delete operation
        # Safe to reuse within this request since we fetch->find->delete atomically
        cache = JDPackageCache(shared_state.get_device())

        packages = get_packages(shared_state, _cache=cache, auto_start=False)
        package_lists = {
            "queue": packages.get("queue", []),
            "history": packages.get("history", []),
        }

        matches = []

        # 1. Try to find by ID
        for _package_location, package_collection in package_lists.items():
            for package in package_collection:
                if str(package.get("nzo_id", "")) == str(package_id):
                    matches.append(package)

        # 2. If not found by ID, try to find by Title
        if not matches and package_title:
            debug(
                f"delete_package: ID '{package_id}' not found, trying title '{package_title}'"
            )
            for package_location, package_collection in package_lists.items():
                for package in package_collection:
                    # Queue items use 'filename', History items use 'name'
                    name = (
                        package.get("filename")
                        if package_location == "queue"
                        else package.get("name")
                    )

                    # Clean up name for comparison if in queue (remove status prefixes)
                    if package_location == "queue" and name:
                        for prefix in [
                            "[Downloading] ",
                            "[Extracting] ",
                            "[Paused] ",
                            "[Linkgrabber] ",
                            "[CAPTCHA not solved!] ",
                        ]:
                            name = name.replace(prefix, "")

                    if name and package_title:
                        normalized_name = " ".join(str(name).split()).lower()
                        normalized_title = " ".join(str(package_title).split()).lower()
                        if (
                            normalized_name == normalized_title
                            or normalized_name in normalized_title
                            or normalized_title in normalized_name
                        ):
                            matches.append(package)

        if not matches:
            if missing_ok:
                info(f"Package {package_id} already absent; delete treated as complete")
                return True
            info(f"Failed to delete package {package_id} - not found by ID or Title")
            return False

        success = False
        for package in matches:
            package_type = package.get("type")
            package_uuid = package.get("uuid")

            # Get title for logging
            deleted_title = package.get("filename") or package.get("name") or "Unknown"

            debug(
                f"delete_package: Found package to delete - type={package_type}, uuid={package_uuid}, package={package}"
            )

            # Perform deletion based on package type
            if package_type in ["linkgrabber", "downloader"]:
                if not package_uuid:
                    debug(
                        f"delete_package: Cannot delete {package_type} package - UUID is missing"
                    )
                    continue

                # Collect link IDs if available in cache
                lg_link_ids = []
                dl_link_ids = []

                if package_type == "linkgrabber":
                    lg_link_ids = get_links_matching_package_uuid(
                        package, cache.linkgrabber_links
                    )
                elif package_type == "downloader":
                    dl_link_ids = get_links_matching_package_uuid(
                        package, cache.downloader_links
                    )

                debug(
                    f"delete_package: Deleting package {package_uuid} from BOTH Linkgrabber and Downloader"
                )

                # 1. Delete from Linkgrabber
                try:
                    shared_state.get_device().linkgrabber.cleanup(
                        "DELETE_ALL",
                        "REMOVE_LINKS_AND_DELETE_FILES",
                        "SELECTED",
                        lg_link_ids,
                        [package_uuid],
                    )
                except Exception as e:
                    debug(f"delete_package: Linkgrabber cleanup failed: {e}")

                # 2. Delete from Downloader
                try:
                    shared_state.get_device().downloads.cleanup(
                        "DELETE_ALL",
                        "REMOVE_LINKS_AND_DELETE_FILES",
                        "SELECTED",
                        dl_link_ids,
                        [package_uuid],
                    )
                except Exception as e:
                    debug(f"delete_package: Downloads cleanup failed: {e}")

                # 3. Verify deletion from BOTH with polling.
                # JDownloader cleanup is asynchronous and may need a few seconds.
                lg_gone = False
                dl_gone = False
                verification_deadline = time.time() + 15

                while time.time() < verification_deadline:
                    lg_gone = False
                    dl_gone = False

                    try:
                        current_lg_packages = (
                            shared_state.get_device().linkgrabber.query_packages()
                        )
                        lg_gone = not any(
                            p.get("uuid") == package_uuid for p in current_lg_packages
                        )
                    except Exception:
                        lg_gone = False

                    try:
                        current_dl_packages = (
                            shared_state.get_device().downloads.query_packages()
                        )
                        dl_gone = not any(
                            p.get("uuid") == package_uuid for p in current_dl_packages
                        )
                    except Exception:
                        dl_gone = False

                    if lg_gone and dl_gone:
                        break

                    time.sleep(0.5)

                if not lg_gone:
                    info(
                        f"Verification failed: Package {deleted_title} still exists in linkgrabber"
                    )
                if not dl_gone:
                    info(
                        f"Verification failed: Package {deleted_title} still exists in downloader"
                    )

                if lg_gone and dl_gone:
                    info(f"Deleted package <y>{deleted_title}</y> from JDownloader")
                    success = True

            elif package_type in ["protected", "failed"]:
                db_id = package.get("nzo_id")
                if not db_id:
                    debug(
                        f"delete_package: Cannot delete {package_type} package - ID is missing"
                    )
                    continue

                debug(
                    f"delete_package: Deleting {db_id} from BOTH Protected and Failed DBs"
                )

                # 1. Delete from Protected
                try:
                    shared_state.get_db("protected").delete(db_id)
                except Exception as e:
                    debug(f"delete_package: Protected DB delete exception: {e}")

                # 2. Delete from Failed
                try:
                    shared_state.get_db("failed").delete(db_id)
                except Exception as e:
                    debug(f"delete_package: Failed DB delete exception: {e}")

                # 3. Verify deletion from BOTH
                protected_exists = shared_state.get_db("protected").retrieve(db_id)
                failed_exists = shared_state.get_db("failed").retrieve(db_id)

                if protected_exists:
                    info(
                        f"Verification failed: Package {deleted_title} still exists in protected DB"
                    )

                if failed_exists:
                    info(
                        f"Verification failed: Package {deleted_title} still exists in failed DB"
                    )

                if not protected_exists and not failed_exists:
                    info(f"Deleted package <y>{deleted_title}</y> from DBs")
                    success = True

        return success

    except Exception as e:
        info(f"Failed to delete package {package_id}")
        debug(f"delete_package: Exception during deletion: {type(e).__name__}: {e}")
        debug(f"delete_package: Traceback: {traceback.format_exc()}")
        return False
