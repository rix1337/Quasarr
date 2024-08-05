# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.downloads.sources.nx import get_nx_download_links
from quasarr.providers.myjd_api import TokenExpiredException, RequestTimeoutException, MYJDException


def get_packages(shared_state):
    packages = []

    protected_packages = shared_state.get_db("to_decrypt").retrieve_all_titles()  # todo not implemented yet
    if protected_packages:
        for package in protected_packages:
            packages.append({
                "details": package,
                "location": "queue",
                "type": "protected"
            })
    try:
        linkgrabber_packages = shared_state.get_device().linkgrabber.query_packages()
    except (TokenExpiredException, RequestTimeoutException, MYJDException):
        linkgrabber_packages = []

    if linkgrabber_packages:
        for package in linkgrabber_packages:
            packages.append({
                "details": package,
                "location": "queue",
                "type": "linkgrabber"
            })
    try:
        downloader_packages = shared_state.get_device().downloads.query_packages()
    except (TokenExpiredException, RequestTimeoutException, MYJDException):
        downloader_packages = []

    if downloader_packages:
        for package in downloader_packages:
            finished = False
            try:
                finished = package["finished"]
            except KeyError:
                pass
            packages.append({
                "details": package,
                "location": "history" if finished else "queue",
                "type": "downloader"
            })

    downloads = {
        "queue": [],
        "history": []
    }
    for package in packages:
        queue_index = 0
        history_index = 0

        def format_eta(seconds):
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            return f"{hours:02}:{minutes:02}:{seconds:02}"

        if package["location"] == "queue":
            time_left = "2385:09:09"  # to signify that its not running
            if package["type"] == "protected":  # todo load from db
                details = package["details"]
                name = "Protected package"
                mb = 1000
                mb_left = mb
                nzo_id = "Quasarr_protected_1"
            elif package["type"] == "linkgrabber":
                details = package["details"]
                name = details["name"]
                mb = int(details["bytesTotal"]) / (1024 * 1024)
                mb_left = mb
                nzo_id = "Quasarr_protected_234"
            elif package["type"] == "downloader":
                details = package["details"]
                name = details["name"]
                try:
                    if details["eta"]:
                        time_left = format_eta(int(details["eta"]))
                except KeyError:
                    pass
                mb = int(details["bytesTotal"]) / (1024 * 1024)
                mb_left = (int(details["bytesTotal"]) - int(details["bytesLoaded"])) / (1024 * 1024)
                nzo_id = "Quasarr_protected_2"

            try:
                downloads["queue"].append({
                    "index": queue_index,
                    "nzo_id": nzo_id,
                    "priority": "Normal",
                    "filename": name,
                    "cat": "movies",
                    "mbleft": int(mb_left),
                    "mb": int(mb),
                    "status": "Downloading",
                    "timeleft": time_left,
                })
            except:
                print(f"Parameters missing for {package}")
            queue_index += 1
        elif package["location"] == "history":
            package = package["details"]
            name = package["name"]
            bytes = int(package["bytesLoaded"])
            storage = package["saveTo"]
            downloads["history"].append({
                "fail_message": "",
                "category": "movies",
                "storage": storage,
                "status": "Completed",
                "nzo_id": "Quasarr_nzo_3",
                "name": name,
                "bytes": int(bytes),
            })
            history_index += 1
        else:
            print(f"Invalid package location {package['location']}")

    return downloads


def download_package(shared_state, title, url):
    package_id = ""

    nx = shared_state.values["config"]("Hostnames").get("nx")
    if nx.lower() in url.lower():
        links = get_nx_download_links(shared_state, url, title)
        print(f"Decrypted {len(links)} download links for {title}")

        download_links = str(links).replace(" ", "")
        download_path = "Quasarr/<jd:packagename>"
        package_id = f"Quasarr_decrypted_{str(hash(title + url)).replace("-", "")}"

        added = shared_state.get_device().linkgrabber.add_links(params=[
            {
                "autostart": True,
                "links": download_links,
                "packageName": title,
                "extractPassword": nx,
                "priority": "DEFAULT",
                "downloadPassword": nx,
                "destinationFolder": download_path,
                "comment": package_id,
                "overwritePackagizerRules": True
            }
        ])
        if not added:
            print(f"Failed to add {title} to linkgrabber")
            package_id = ""

    # Todo links are protected -> add them to the database for decryption in the web ui

    return package_id


def delete_package(shared_state, package_id):
    deleted = False
    # todo implement (detect package by id from jdownloader or table)
    # delete it at the correct location
    return deleted
