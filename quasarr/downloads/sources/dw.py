# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info


def get_dw_download_links(shared_state, url, title):
    dw = shared_state.values["config"]("Hostnames").get("dw")
    ajax_url = "https://" + dw + "/wp-admin/admin-ajax.php"

    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    session = requests.Session()

    try:
        request = session.get(url, headers=headers, timeout=10)
        content = BeautifulSoup(request.text, "html.parser")
        download_buttons = content.find_all("button", {"class": "show_link"})
    except:
        info(f"DW site has been updated. Grabbing download links for {title} not possible!")
        return False

    download_links = []
    try:
        for button in download_buttons:
            payload = f"action=show_link&link_id={button['value']}"
            headers = {
                'User-Agent': shared_state.values["user_agent"],
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
            }

            response = session.post(ajax_url, payload, headers=headers, timeout=10)
            if response.status_code != 200:
                info(f"DW site has been updated. Grabbing download links for {title} not possible!")
                continue
            else:
                response = response.json()
                link = response["data"].split(",")[0]

                if dw in link:
                    match = re.search(r'https://' + dw + r'/azn/af\.php\?v=([A-Z0-9]+)(#.*)?', link)
                    if match:
                        link = (f'https://filecrypt.cc/Container/{match.group(1)}'
                                f'.html{match.group(2) if match.group(2) else ""}')

                hoster = button.nextSibling.img["src"].split("/")[-1].replace(".png", "")
                download_links.append([link, hoster])
    except:
        info(f"DW site has been updated. Parsing download links for {title} not possible!")
        pass

    return download_links
