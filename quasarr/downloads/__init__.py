# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

from quasarr.downloads.sources.dw import get_dw_download_links
from quasarr.downloads.sources.nx import get_nx_download_links
from quasarr.providers.myjd_api import TokenExpiredException, RequestTimeoutException, MYJDException
from quasarr.providers.notifications import send_discord_captcha_alert


def get_first_matching_comment(package, package_links):
    package_uuid = package.get("uuid")
    if package_uuid:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                return link.get("comment")
    return None


def get_links_matching_package_uuid(package, package_links):
    package_uuid = package.get("uuid")
    link_ids = []
    if package_uuid:
        for link in package_links:
            if link.get("packageUUID") == package_uuid:
                link_ids.append(link.get("uuid"))
    return link_ids


def format_eta(seconds):
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
            comment = get_first_matching_comment(package, shared_state.get_device().linkgrabber.query_links())
            packages.append({
                "details": package,
                "location": "queue",
                "type": "linkgrabber",
                "comment": comment,
                "uuid": package.get("uuid")
            })
    try:
        downloader_packages = shared_state.get_device().downloads.query_packages()
    except (TokenExpiredException, RequestTimeoutException, MYJDException):
        downloader_packages = []

    if downloader_packages:
        for package in downloader_packages:
            comment = get_first_matching_comment(package, shared_state.get_device().downloads.query_links())
            status = package.get("status", "")

            if any(ex_str in status.lower() for ex_str in ["entpacken", "extracting"]) and "ok:" not in status.lower():
                finished = False
            else:
                finished = package.get("finished", False)

            packages.append({
                "details": package,
                "location": "history" if finished else "queue",
                "type": "downloader",
                "comment": comment,
                "uuid": package.get("uuid")
            })

    downloads = {
        "queue": [],
        "history": []
    }
    for package in packages:
        queue_index = 0
        history_index = 0

        if package["location"] == "queue":
            time_left = "2376:00:00"  # yields "99d" to signify that its not running
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
                name = f"[Downloading] {details["name"]}"
                try:
                    if details["eta"]:
                        time_left = format_eta(int(details["eta"]))
                except KeyError:
                    name = name.replace("[Downloading]", "[Paused]")
                try:
                    mb = int(details["bytesTotal"]) / (1024 * 1024)
                    mb_left = (int(details["bytesTotal"]) - int(details["bytesLoaded"])) / (1024 * 1024)
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
                print(f"Parameters missing for {package}")
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

            downloads["history"].append({
                "fail_message": "",
                "category": category,
                "storage": storage,
                "status": "Completed",
                "nzo_id": package_id,
                "name": name,
                "bytes": int(size),
                "type": "downloader",
                "uuid": package["uuid"]
            })
            history_index += 1
        else:
            print(f"Invalid package location {package['location']}")

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
                    shared_state.get_device().downloads.remove_links(ids, [package["uuid"]])
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
        print(f"Deleted package {deleted} with ID {package_id}")
    else:
        print(f"Failed to delete package {package_id}")
    return deleted


def download_package(shared_state, request_from, title, url, size_mb, password):
    if "radarr".lower() in request_from.lower():
        category = "movies"
    else:
        category = "tv"

    package_id = ""

    dw = shared_state.values["config"]("Hostnames").get("dw")
    nx = shared_state.values["config"]("Hostnames").get("nx")

    if nx.lower() in url.lower():
        links = get_nx_download_links(shared_state, url, title)
        print(f"Decrypted {len(links)} download links for {title}")
        package_id = f"Quasarr_{category}_{str(hash(title + url)).replace('-', '')}"

        added = shared_state.download_package(links, title, password, package_id)

        if not added:
            print(f"Failed to add {title} to linkgrabber")
            package_id = None

    elif dw.lower() in url.lower():
        links = get_dw_download_links(shared_state, url, title)
        print(f"CAPTCHA-Solution required for {title} - {shared_state.values['external_address']}/captcha")
        send_discord_captcha_alert(shared_state, title)
        package_id = f"Quasarr_{category}_{str(hash(title + str(links))).replace('-', '')}"
        blob = json.dumps({"title": title, "links": links, "size_mb": size_mb, "password": password})
        shared_state.values["database"]("protected").update_store(package_id, blob)

    elif "filecrypt".lower() in url.lower():
        print(f"CAPTCHA-Solution required for {title} - {shared_state.values['external_address']}/captcha")
        send_discord_captcha_alert(shared_state, title)
        package_id = f"Quasarr_{category}_{str(hash(title + url)).replace('-', '')}"
        blob = json.dumps({"title": title, "links": [[url, "filecrypt"]], "size_mb": size_mb, "password": password})
        shared_state.values["database"]("protected").update_store(package_id, blob)

    return package_id
