# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
from collections import defaultdict
from urllib.parse import urlparse

from quasarr.providers.log import info, debug
from quasarr.providers.myjd_api import TokenExpiredException, RequestTimeoutException, MYJDException


def get_links_comment(package, package_links):
    package_uuid = package.get("uuid")
    if package_uuid and package_links:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                return link.get("comment")
    return None


def get_links_status(package, all_links, is_archive=False):
    links_in_package = []
    package_uuid = package.get("uuid")
    if package_uuid and all_links:
        for link in all_links:
            link_package_uuid = link.get("packageUUID")
            if link_package_uuid and link_package_uuid == package_uuid:
                links_in_package.append(link)

    all_finished = True
    eta = None
    error = None

    mirrors = defaultdict(list)
    for link in links_in_package:
        url = link.get("url", "")
        base_domain = urlparse(url).netloc
        mirrors[base_domain].append(link)

    has_mirror_all_online = False
    for mirror_links in mirrors.values():
        if all(link.get('availability', '').lower() == 'online' for link in mirror_links):
            has_mirror_all_online = True
            break

    offline_links = [link for link in links_in_package if link.get('availability', '').lower() == 'offline']
    offline_ids = [link.get('uuid') for link in offline_links]
    offline_mirror_linkids = offline_ids if has_mirror_all_online else []

    for link in links_in_package:
        if link.get('availability', "").lower() == "offline" and not has_mirror_all_online:
            error = "Links offline for all mirrors"
        if link.get('statusIconKey', '').lower() == "false":
            error = "File error in package"
        link_finished = link.get('finished', False)
        link_extraction_status = link.get('extractionStatus', '').lower()  # "error" signifies an issue
        link_eta = link.get('eta', 0) // 1000
        if not link_finished:
            all_finished = False
        elif link_extraction_status and link_extraction_status != 'successful':
            if link_extraction_status == 'error':
                error = link.get('status', '')
            elif link_extraction_status == 'running' and link_eta > 0:
                if eta and link_eta > eta or not eta:
                    eta = link_eta
            all_finished = False
        elif is_archive:
            # For archives, check if extraction is actually complete
            link_status = link.get('status', '').lower()
            # Check for various "extraction complete" indicators
            if 'extraction ok' not in link_status and 'entpacken ok' not in link_status:
                all_finished = False

    return {"all_finished": all_finished, "eta": eta, "error": error, "offline_mirror_linkids": offline_mirror_linkids}


def get_links_matching_package_uuid(package, package_links):
    package_uuid = package.get("uuid")
    link_ids = []

    if not isinstance(package_links, list):
        debug("Error - expected a list of package_links, got: %r" % type(package_links).__name__)
        return link_ids

    if package_uuid:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                link_ids.append(link.get("uuid"))
    else:
        info("Error - package uuid missing in delete request!")
    return link_ids


def format_eta(seconds):
    if seconds < 0:
        return "23:59:59"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"


def get_packages(shared_state):
    packages = []

    protected_packages = shared_state.get_db("protected").retrieve_all_titles()
    if protected_packages:
        for package in protected_packages:
            package_id = package[0]

            data = json.loads(package[1])
            details = {
                "title": data["title"],
                "urls": data["links"],
                "size_mb": data["size_mb"],
                "password": data["password"]
            }

            packages.append({
                "details": details,
                "location": "queue",
                "type": "protected",
                "package_id": package_id
            })

    failed_packages = shared_state.get_db("failed").retrieve_all_titles()
    if failed_packages:
        for package in failed_packages:
            package_id = package[0]

            data = json.loads(package[1])
            try:
                if type(data) is str:
                    data = json.loads(data)
            except json.JSONDecodeError:
                pass
            details = {
                "name": data["title"],
                "bytesLoaded": 0,
                "saveTo": "/"
            }

            error = data.get("error", "Unknown error")

            packages.append({
                "details": details,
                "location": "history",
                "type": "failed",
                "error": error,
                "comment": package_id,
                "uuid": package_id
            })
    try:
        linkgrabber_packages = shared_state.get_device().linkgrabber.query_packages()
        linkgrabber_links = shared_state.get_device().linkgrabber.query_links()
    except (TokenExpiredException, RequestTimeoutException, MYJDException):
        linkgrabber_packages = []
        linkgrabber_links = []

    if linkgrabber_packages:
        for package in linkgrabber_packages:
            comment = get_links_comment(package, shared_state.get_device().linkgrabber.query_links())
            link_details = get_links_status(package, linkgrabber_links, is_archive=False)

            error = link_details["error"]
            offline_mirror_linkids = link_details["offline_mirror_linkids"]
            if offline_mirror_linkids:
                shared_state.get_device().linkgrabber.cleanup(
                    "DELETE_OFFLINE",
                    "REMOVE_LINKS_ONLY",
                    "SELECTED",
                    offline_mirror_linkids,
                    [package["uuid"]]
                )

            location = "history" if error else "queue"
            packages.append({
                "details": package,
                "location": location,
                "type": "linkgrabber",
                "comment": comment,
                "uuid": package.get("uuid"),
                "error": error
            })
    try:
        downloader_packages = shared_state.get_device().downloads.query_packages()
        downloader_links = shared_state.get_device().downloads.query_links()
    except (TokenExpiredException, RequestTimeoutException, MYJDException):
        downloader_packages = []
        downloader_links = []

    if downloader_packages and downloader_links:
        for package in downloader_packages:
            comment = get_links_comment(package, downloader_links)

            # Check if package is actually archived/extracted using archive info
            is_archive = False
            try:
                archive_info = shared_state.get_device().extraction.get_archive_info([], [package.get("uuid")])
                is_archive = True if archive_info and archive_info[0] else False
            except:
                # On error, don't assume it's an archive - check bytes instead
                pass

            link_details = get_links_status(package, downloader_links, is_archive)

            error = link_details["error"]
            finished = link_details["all_finished"]

            # Additional check: if download is 100% complete and no ETA, it's finished
            # This catches non-archive packages or when archive detection fails
            if not finished and not error:
                bytes_total = int(package.get("bytesTotal", 0))
                bytes_loaded = int(package.get("bytesLoaded", 0))
                eta = package.get("eta")

                # If download is complete and no ETA (paused/finished state)
                if bytes_total > 0 and bytes_loaded >= bytes_total and eta is None:
                    # Only mark as finished if it's not an archive, or if we can't detect archives
                    if not is_archive:
                        finished = True

            if not finished and link_details["eta"]:
                package["eta"] = link_details["eta"]

            location = "history" if error or finished else "queue"

            packages.append({
                "details": package,
                "location": location,
                "type": "downloader",
                "comment": comment,
                "uuid": package.get("uuid"),
                "error": error
            })

    downloads = {
        "queue": [],
        "history": []
    }
    for package in packages:
        queue_index = 0
        history_index = 0

        package_id = None

        if package["location"] == "queue":
            time_left = "23:59:59"
            if package["type"] == "linkgrabber":
                details = package["details"]
                name = f"[Linkgrabber] {details["name"]}"
                try:
                    mb = mb_left = int(details["bytesTotal"]) / (1024 * 1024)
                except KeyError:
                    mb = mb_left = 0
                try:
                    package_id = package["comment"]
                    if "movies" in package_id:
                        category = "movies"
                    elif "docs" in package_id:
                        category = "docs"
                    else:
                        category = "tv"
                except TypeError:
                    category = "not_quasarr"
                package_type = "linkgrabber"
                package_uuid = package["uuid"]
            elif package["type"] == "downloader":
                details = package["details"]
                status = "Downloading"
                eta = details.get("eta")
                bytes_total = int(details.get("bytesTotal", 0))
                bytes_loaded = int(details.get("bytesLoaded", 0))

                mb = bytes_total / (1024 * 1024)
                mb_left = (bytes_total - bytes_loaded) / (1024 * 1024) if bytes_total else 0
                if mb_left < 0:
                    mb_left = 0

                if eta is None:
                    status = "Paused"
                else:
                    time_left = format_eta(int(eta))
                    if mb_left == 0:
                        status = "Extracting"

                name = f"[{status}] {details['name']}"

                try:
                    package_id = package["comment"]
                    if "movies" in package_id:
                        category = "movies"
                    elif "docs" in package_id:
                        category = "docs"
                    else:
                        category = "tv"
                except TypeError:
                    category = "not_quasarr"
                package_type = "downloader"
                package_uuid = package["uuid"]
            else:
                details = package["details"]
                name = f"[CAPTCHA not solved!] {details["title"]}"
                mb = mb_left = details["size_mb"]
                try:
                    package_id = package["package_id"]
                    if "movies" in package_id:
                        category = "movies"
                    elif "docs" in package_id:
                        category = "docs"
                    else:
                        category = "tv"
                except TypeError:
                    category = "not_quasarr"
                package_type = "protected"
                package_uuid = None

            try:
                if package_id:
                    mb_left = int(mb_left)
                    mb = int(mb)
                    try:
                        percentage = int(100 * (mb - mb_left) / mb)
                    except ZeroDivisionError:
                        percentage = 0

                    downloads["queue"].append({
                        "index": queue_index,
                        "nzo_id": package_id,
                        "priority": "Normal",
                        "filename": name,
                        "cat": category,
                        "mbleft": mb_left,
                        "mb": mb,
                        "status": "Downloading",
                        "percentage": percentage,
                        "timeleft": time_left,
                        "type": package_type,
                        "uuid": package_uuid
                    })
            except:
                debug(f"Parameters missing for {package}")
            queue_index += 1
        elif package["location"] == "history":
            details = package["details"]
            name = details["name"]
            try:
                size = int(details["bytesLoaded"])
            except KeyError:
                size = 0
            storage = details["saveTo"]
            try:
                package_id = package["comment"]
                if "movies" in package_id:
                    category = "movies"
                elif "docs" in package_id:
                    category = "docs"
                else:
                    category = "tv"
            except TypeError:
                category = "not_quasarr"

            error = package.get("error")
            fail_message = ""
            if error:
                status = "Failed"
                fail_message = error
            else:
                status = "Completed"

            downloads["history"].append({
                "fail_message": fail_message,
                "category": category,
                "storage": storage,
                "status": status,
                "nzo_id": package_id,
                "name": name,
                "bytes": int(size),
                "percentage": 100,
                "type": "downloader",
                "uuid": package["uuid"]
            })
            history_index += 1
        else:
            info(f"Invalid package location {package['location']}")

    if not shared_state.get_device().linkgrabber.is_collecting():
        linkgrabber_packages = shared_state.get_device().linkgrabber.query_packages()
        linkgrabber_links = shared_state.get_device().linkgrabber.query_links()

        packages_to_start = []
        links_to_start = []

        for package in linkgrabber_packages:
            comment = get_links_comment(package, shared_state.get_device().linkgrabber.query_links())
            if comment and comment.startswith("Quasarr_"):
                package_uuid = package.get("uuid")
                if package_uuid:
                    linkgrabber_links = [link.get("uuid") for link in linkgrabber_links if
                                         link.get("packageUUID") == package_uuid]
                    if linkgrabber_links:
                        packages_to_start.append(package_uuid)
                        links_to_start.extend(linkgrabber_links)
                    else:
                        info(f"Package {package_uuid} has no links in linkgrabber - skipping start")

                    break

        if packages_to_start and links_to_start:
            shared_state.get_device().linkgrabber.move_to_downloadlist(links_to_start, packages_to_start)
            info(f"Started {len(packages_to_start)} package download"
                 f"{'s' if len(packages_to_start) > 1 else ''} from linkgrabber")

    return downloads


def delete_package(shared_state, package_id):
    try:
        deleted_title = ""

        packages = get_packages(shared_state)
        for package_location in packages:
            for package in packages[package_location]:
                if package["nzo_id"] == package_id:
                    if package["type"] == "linkgrabber":
                        ids = get_links_matching_package_uuid(package,
                                                              shared_state.get_device().linkgrabber.query_links())
                        if ids:
                            shared_state.get_device().linkgrabber.cleanup(
                                "DELETE_ALL",
                                "REMOVE_LINKS_AND_DELETE_FILES",
                                "SELECTED",
                                ids,
                                [package["uuid"]]
                            )
                            break
                    elif package["type"] == "downloader":
                        ids = get_links_matching_package_uuid(package,
                                                              shared_state.get_device().downloads.query_links())
                        if ids:
                            shared_state.get_device().downloads.cleanup(
                                "DELETE_ALL",
                                "REMOVE_LINKS_AND_DELETE_FILES",
                                "SELECTED",
                                ids,
                                [package["uuid"]]
                            )
                            break

                    # no state check, just clean up whatever exists with the package id
                    shared_state.get_db("failed").delete(package_id)
                    shared_state.get_db("protected").delete(package_id)

                    if package_location == "queue":
                        package_name_field = "filename"
                    else:
                        package_name_field = "name"

                    try:
                        deleted_title = package[package_name_field]
                    except KeyError:
                        pass

                    # Leave the loop
                    break

        if deleted_title:
            info(f'Deleted package "{deleted_title}" with ID "{package_id}"')
        else:
            info(f'Deleted package "{package_id}"')
    except:
        info(f"Failed to delete package {package_id}")
        return False
    return True
