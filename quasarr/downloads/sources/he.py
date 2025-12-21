# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug

hostname = "he"


def get_he_download_links(shared_state, url, mirror, title):
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    session = requests.Session()

    try:
        resp = session.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        info(f"{hostname}: could not fetch release for {title}: {e}")
        return False

    imdb_id = None
    try:
        imdb_link = soup.find('a', href=re.compile(r"imdb\.com/title/tt\d+", re.IGNORECASE))
        if imdb_link:
            href = imdb_link['href'].strip()
            m = re.search(r"(tt\d{4,7})", href)
            if m:
                imdb_id = m.group(1)
            else:
                debug(f"{hostname}: imdb_id not found for title {title} in link href.")
        else:
            debug(f"{hostname}: imdb_id link href not found for title {title}.")
    except Exception:
        debug(f"{hostname}: failed to extract imdb_id for title {title}.")

    anchors = []
    for retries in range(10):
        form = soup.find('form', id=re.compile(r'content-protector-access-form'))
        if not form:
            return False

        action = form.get('action') or url
        action_url = urljoin(resp.url, action)

        payload = {}
        for inp in form.find_all('input'):
            name = inp.get('name')
            if not name:
                continue
            value = inp.get('value', '')
            payload[name] = value

        append_patt = re.compile(r"append\(\s*[\'\"](?P<key>[^\'\"]+)[\'\"]\s*,\s*[\'\"](?P<val>[^\'\"]+)[\'\"]\s*\)",
                                 re.IGNORECASE)

        for script in soup.find_all('script'):
            txt = script.string if script.string is not None else script.get_text()
            if not txt:
                continue
            for m in append_patt.finditer(txt):
                payload[m.group('key')] = m.group('val')

        post_headers = headers.copy()
        post_headers.update({'Referer': resp.url})
        try:
            resp = session.post(action_url, data=payload, headers=post_headers, timeout=30)
            soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            info(f"{hostname}: could not submit protector form for {title}: {e}")
            break

        unlocked = soup.select('.content-protector-access-form')
        if unlocked:
            for u in unlocked:
                anchors.extend(u.find_all('a', href=True))

        if anchors:
            break

    links = []
    for a in anchors:
        try:
            href = a['href'].strip()

            netloc = urlparse(href).netloc
            hoster = netloc.split(':')[0].lower()
            parts = hoster.split('.')
            if len(parts) >= 2:
                hoster = parts[-2]

            links.append([href, hoster])
        except Exception:
            debug(f"{hostname}: could not resolve download link hoster for {title}")
            continue

    if not links:
        info(f"No external download links found on {hostname} page for {title}")
        return False

    return {
        "links": links,
        "imdb_id": imdb_id,
    }
