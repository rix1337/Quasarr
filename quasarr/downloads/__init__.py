# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

from quasarr.downloads.sources.dd import get_dd_download_links
from quasarr.downloads.sources.dw import get_dw_download_links
from quasarr.downloads.sources.nx import get_nx_download_links
from quasarr.downloads.sources.sf import get_release_url, resolve_sf_redirect
from quasarr.providers.log import info, debug
from quasarr.providers.myjd_api import TokenExpiredException, RequestTimeoutException, MYJDException
from quasarr.providers.notifications import send_discord_message


def get_links_comment(package, package_links):
    package_uuid = package.get("uuid")
    if package_uuid and package_links:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                return link.get("comment")
    return None


def get_links_status(package, all_links):
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

    for link in links_in_package:
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

    return {"all_finished": all_finished, "eta": eta, "error": error}


def get_links_matching_package_uuid(package, package_links):
    package_uuid = package.get("uuid")
    link_ids = []
    if package_uuid:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                link_ids.append(link.get("uuid"))
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
    try:
        linkgrabber_packages = shared_state.get_device().linkgrabber.query_packages()
    except (TokenExpiredException, RequestTimeoutException, MYJDException):
        linkgrabber_packages = []

    if linkgrabber_packages:
        for package in linkgrabber_packages:
            comment = get_links_comment(package, shared_state.get_device().linkgrabber.query_links())
            packages.append({
                "details": package,
                "location": "queue",
                "type": "linkgrabber",
                "comment": comment,
                "uuid": package.get("uuid")
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
            all_finished = get_links_status(package, downloader_links)

            error = all_finished["error"]
            finished = all_finished["all_finished"]
            if not finished and all_finished["eta"]:
                package["eta"] = all_finished["eta"]

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
                    else:
                        category = "tv"
                except TypeError:
                    category = "not_quasarr"
                package_type = "protected"
                package_uuid = None

            try:
                if package_id:
                    downloads["queue"].append({
                        "index": queue_index,
                        "nzo_id": package_id,
                        "priority": "Normal",
                        "filename": name,
                        "cat": category,
                        "mbleft": int(mb_left),
                        "mb": int(mb),
                        "status": "Downloading",
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
            size = int(details["bytesLoaded"])
            storage = details["saveTo"]
            try:
                package_id = package["comment"]
                if "movies" in package_id:
                    category = "movies"
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
                "type": "downloader",
                "uuid": package["uuid"]
            })
            history_index += 1
        else:
            info(f"Invalid package location {package['location']}")

    return downloads


def delete_package(shared_state, package_id):
    deleted = ""

    packages = get_packages(shared_state)
    for package_location in packages:
        for package in packages[package_location]:
            if package["nzo_id"] == package_id:
                if package["type"] == "linkgrabber":
                    ids = get_links_matching_package_uuid(package, shared_state.get_device().linkgrabber.query_links())
                    shared_state.get_device().linkgrabber.remove_links(ids, [package["uuid"]])
                elif package["type"] == "downloader":
                    ids = get_links_matching_package_uuid(package, shared_state.get_device().downloads.query_links())
                    shared_state.get_device().downloads.cleanup(
                        "DELETE_ALL",
                        "REMOVE_LINKS_AND_DELETE_FILES",
                        "SELECTED",
                        ids,
                        [package["uuid"]]
                    )
                else:
                    shared_state.get_db("protected").delete(package_id)
                if package_location == "queue":
                    package_name_field = "filename"
                else:
                    package_name_field = "name"

                deleted = package[package_name_field]
                break
        if deleted:
            break

    if deleted:
        info(f'Deleted package "{deleted}" with ID "{package_id}"')
    else:
        info(f'Failed to delete package "{package_id}"')
    return deleted


def download(shared_state, request_from, title, url, size_mb, password, imdb_id=None):
    if "radarr".lower() in request_from.lower():
        category = "movies"
    else:
        category = "tv"

    package_id = f"Quasarr_{category}_{str(hash(title + url)).replace('-', '')}"

    if imdb_id is not None and imdb_id.lower() == "none":
        imdb_id = None

    dd = shared_state.values["config"]("Hostnames").get("dd")
    dw = shared_state.values["config"]("Hostnames").get("dw")
    nx = shared_state.values["config"]("Hostnames").get("nx")
    sf = shared_state.values["config"]("Hostnames").get("sf")

    if dd and dd.lower() in url.lower():
        links = get_dd_download_links(shared_state, title)
        if links:
            info(f"Decrypted {len(links)} download links for {title}")
            send_discord_message(shared_state, title=title, case="unprotected", imdb_id=imdb_id)
            added = shared_state.download_package(links, title, password, package_id)
            if not added:
                info(f"Failed to add {title} to linkgrabber")
                package_id = None
        else:
            info(f"Found 0 links decrypting {title}")
            package_id = None

    elif nx and nx.lower() in url.lower():
        links = get_nx_download_links(shared_state, url, title)
        if links:
            info(f"Decrypted {len(links)} download links for {title}")
            send_discord_message(shared_state, title=title, case="unprotected", imdb_id=imdb_id)
            added = shared_state.download_package(links, title, password, package_id)
            if not added:
                info(f"Failed to add {title} to linkgrabber")
                package_id = None
        else:
            info(f"Found 0 links decrypting {title}")
            package_id = None

    elif dw and dw.lower() in url.lower():
        links = get_dw_download_links(shared_state, url, title)
        info(f'CAPTCHA-Solution required for "{title}" at: {shared_state.values['external_address']}/captcha')
        send_discord_message(shared_state, title=title, case="captcha", imdb_id=imdb_id)
        blob = json.dumps({"title": title, "links": links, "size_mb": size_mb, "password": password})
        shared_state.values["database"]("protected").update_store(package_id, blob)

    elif sf and sf.lower() in url.lower():
        if f"https://{sf}/external" in url:
            url = resolve_sf_redirect(url)
        elif url.startswith(f"https://{sf}/"):
            url = get_release_url(url, title, shared_state)

        if url:
            info(f'CAPTCHA-Solution required for "{title}" at: {shared_state.values['external_address']}/captcha')
            send_discord_message(shared_state, title=title, case="captcha", imdb_id=imdb_id)
            blob = json.dumps({"title": title, "links": [[url, "filecrypt"]], "size_mb": size_mb, "password": password})
            shared_state.values["database"]("protected").update_store(package_id, blob)
        else:
            info(f"Failed to get download link from SF for {title} - {url}")
            package_id = None

    elif "filecrypt".lower() in url.lower():
        info(f'CAPTCHA-Solution required for "{title}" at: {shared_state.values['external_address']}/captcha')
        send_discord_message(shared_state, title=title, case="captcha", imdb_id=imdb_id)
        blob = json.dumps({"title": title, "links": [[url, "filecrypt"]], "size_mb": size_mb, "password": password})
        shared_state.values["database"]("protected").update_store(package_id, blob)

    else:
        package_id = None
        info(f"Could not parse URL for {title} - {url}")

    return package_id
