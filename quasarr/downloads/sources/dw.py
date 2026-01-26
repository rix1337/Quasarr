# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info

hostname = "dw"


def get_dw_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    DW source handler - fetches protected download links from DW site.
    """

    dw = shared_state.values["config"]("Hostnames").get("dw")
    ajax_url = "https://" + dw + "/wp-admin/admin-ajax.php"

    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    session = requests.Session()

    try:
        r = session.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        content = BeautifulSoup(r.text, "html.parser")
        download_buttons = content.find_all("button", {"class": "show_link"})
    except Exception as e:
        info(
            f"DW site has been updated. Grabbing download links for {title} not possible!"
        )
        mark_hostname_issue(hostname, "download", str(e))
        return {"links": []}

    download_links = []
    try:
        for button in download_buttons:
            payload = f"action=show_link&link_id={button['value']}"
            headers = {
                "User-Agent": shared_state.values["user_agent"],
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }

            r = session.post(ajax_url, payload, headers=headers, timeout=10)
            r.raise_for_status()

            response = r.json()
            link = response["data"].split(",")[0]

            if dw in link:
                match = re.search(
                    r"https://" + dw + r"/azn/af\.php\?v=([A-Z0-9]+)(#.*)?", link
                )
                if match:
                    link = (
                        f"https://filecrypt.cc/Container/{match.group(1)}"
                        f".html{match.group(2) if match.group(2) else ''}"
                    )

                hoster = (
                    button.nextSibling.img["src"].split("/")[-1].replace(".png", "")
                )
                hoster = (
                    f"1fichier" if hoster.startswith("fichier") else hoster
                )  # align with expected mirror name
                if mirror and mirror.lower() not in hoster.lower():
                    debug(
                        f'Skipping link from "{hoster}" (not the desired mirror "{mirror}")!'
                    )
                    continue

                download_links.append([link, hoster])
    except Exception as e:
        info(
            f"DW site has been updated. Parsing download links for {title} not possible!"
        )
        mark_hostname_issue(hostname, "download", str(e))

    if download_links:
        clear_hostname_issue(hostname)
    return {"links": download_links}
