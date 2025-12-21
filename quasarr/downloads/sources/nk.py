# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info

hostname = "nk"
supported_mirrors = ["rapidgator", "ddownload"]


def get_nk_download_links(shared_state, url, mirror, title):
    host = shared_state.values["config"]("Hostnames").get(hostname)
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    session = requests.Session()

    try:
        resp = session.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        info(f"{hostname}: could not fetch release page for {title}: {e}")
        return False

    anchors = soup.select('a.btn-orange')
    candidates = []
    for a in anchors:
        mirror = a.text.strip().lower()
        if mirror == 'ddl.to':
            mirror = 'ddownload'

        if mirror not in supported_mirrors:
            continue

        href = a.get('href', '').strip()
        if not href.lower().startswith(('http://', 'https://')):
            href = 'https://' + host + href

        try:
            href = requests.head(href, headers=headers, allow_redirects=True, timeout=20).url
        except Exception as e:
            info(f"{hostname}: could not resolve download link for {title}: {e}")
            continue

        candidates.append([href, mirror])

    if not candidates:
        info(f"No external download links found on {hostname} page for {title}")

    return candidates
