# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info

SECTIONS = {2000: "filme", 5000: "serien"}


def _release_list(**extra):
    return {
        "item": "h4",
        "title": {"selector": "a"},
        "link": {"selector": "a", "attr": "href"},
        "imdb": {"attr": "html"},
        "size": {"selector": "span", "required": True},
        "date": {
            "within": "article",
            "selector": "span.date.updated",
            "required": True,
        },
        "title_cleanup": "none",
        **extra,
    }


TEMPLATE = {
    "name": "DW",
    "language": "de",
    "feeds": [
        {"category": category, "url": f"https://{{host}}/videos/{section}/"}
        for category, section in SECTIONS.items()
    ],
    "list": _release_list(dedupe=False),
    "search": {
        "mode": "imdb",
        "categories": list(SECTIONS),
        "urls": {
            category: [f"https://{{host}}/?s={{q}}&videocategory={section}"]
            for category, section in SECTIONS.items()
        },
    },
    "search_list": _release_list(dedupe=False),
    "download": {"password": "hostname"},
    # each link sits behind a button the site resolves over AJAX
    "hooks": {"download": "download"},
}


def download(source, shared_state, url, mirrors, title, password):
    """Resolve the AJAX link buttons of a release page."""
    dw = source.hostname
    ajax_url = "https://" + dw + "/wp-admin/admin-ajax.php"

    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    session = requests.Session()

    try:
        r = session.get(
            url,
            headers=headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        content = BeautifulSoup(r.text, "html.parser")
        download_buttons = content.find_all("button", {"class": "show_link"})
    except Exception as e:
        info(
            f"Site has been updated. Grabbing download links for {title} not possible!"
        )
        mark_hostname_issue(source.initials, "download", str(e))
        return {"links": []}

    download_links = []
    try:
        for button in download_buttons:
            payload = f"action=show_link&link_id={button['value']}"
            headers = {
                "User-Agent": shared_state.values["user_agent"],
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }

            r = session.post(
                ajax_url,
                payload,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
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
                    "1fichier" if hoster.startswith("fichier") else hoster
                )  # align with expected mirror name
                if mirrors and not any(m.lower() in hoster.lower() for m in mirrors):
                    debug(
                        f'Skipping link from "{hoster}" (not in desired mirrors "{mirrors}")!'
                    )
                    continue

                download_links.append([link, hoster])
    except Exception as e:
        info(f"Site has been updated. Parsing download links for {title} not possible!")
        mark_hostname_issue(source.initials, "download", str(e))

    if download_links:
        clear_hostname_issue(source.initials)
    return {"links": download_links}
