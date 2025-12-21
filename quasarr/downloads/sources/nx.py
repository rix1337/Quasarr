# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info
from quasarr.providers.sessions.nx import retrieve_and_validate_session


def get_filer_folder_links_via_api(shared_state, url):
    try:
        headers = {
            'User-Agent': shared_state.values["user_agent"],
            'Referer': url
        }

        m = re.search(r"/folder/([A-Za-z0-9]+)", url)
        if not m:
            return url  # not a folder URL

        folder_hash = m.group(1)
        api_url = f"https://filer.net/api/folder/{folder_hash}"

        response = requests.get(api_url, headers=headers, timeout=10)
        if not response or response.status_code != 200:
            return url

        data = response.json()
        files = data.get("files", [])
        links = []

        # Build download URLs from their file hashes
        for f in files:
            file_hash = f.get("hash")
            if not file_hash:
                continue
            dl_url = f"https://filer.net/get/{file_hash}"
            links.append(dl_url)

        # Return extracted links or fallback
        return links if links else url

    except:
        return url


def get_nx_download_links(shared_state, url, mirror, title): # signature must align with other download link functions!
    nx = shared_state.values["config"]("Hostnames").get("nx")

    if f"{nx}/release/" not in url:
        info("Link is not a Release link, could not proceed:" + url)

    nx_session = retrieve_and_validate_session(shared_state)
    if not nx_session:
        info(f"Could not retrieve valid session for {nx}")
        return []

    headers = {
        'User-Agent': shared_state.values["user_agent"],
        'Referer': url
    }

    json_data = {}

    url_segments = url.split('/')
    payload_url = '/'.join(url_segments[:-2]) + '/api/getLinks/' + url_segments[-1]

    payload = nx_session.post(payload_url,
                              headers=headers,
                              json=json_data,
                              timeout=10
                              )

    if payload.status_code == 200:
        try:
            payload = payload.json()
        except:
            info("Invalid response decrypting " + str(title) + " URL: " + str(url))
            shared_state.values["database"]("sessions").delete("nx")
            return []

    if payload and any(key in payload for key in ("err", "error")):
        error_msg = payload.get("err") or payload.get("error")
        info(f"Error decrypting {title!r} URL: {url!r} - {error_msg}")
        shared_state.values["database"]("sessions").delete("nx")
        return []

    try:
        decrypted_url = payload['link'][0]['url']
        if decrypted_url:
            if "filer.net/folder/" in decrypted_url:
                urls = get_filer_folder_links_via_api(shared_state, decrypted_url)
            else:
                urls = [decrypted_url]
            return urls
    except:
        pass

    info("Something went wrong decrypting " + str(title) + " URL: " + str(url))
    shared_state.values["database"]("sessions").delete("nx")
    return []
