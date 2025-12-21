# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import html
import re
from datetime import datetime, timedelta
from json import loads
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug


def get_poster_link(shared_state, imdb_id):
    poster_link = None
    if imdb_id:
        headers = {'User-Agent': shared_state.values["user_agent"]}
        request = requests.get(f"https://www.imdb.com/title/{imdb_id}/", headers=headers, timeout=10).text
        soup = BeautifulSoup(request, "html.parser")
        try:
            poster_set = soup.find('div', class_='ipc-poster').div.img[
                "srcset"]  # contains links to posters in ascending resolution
            poster_links = [x for x in poster_set.split(" ") if
                            len(x) > 10]  # extract all poster links ignoring resolution info
            poster_link = poster_links[-1]  # get the highest resolution poster
        except:
            pass

    if not poster_link:
        debug(f"Could not get poster title for {imdb_id} from IMDb")

    return poster_link


def get_localized_title(shared_state, imdb_id, language='de'):
    localized_title = None

    headers = {
        'Accept-Language': language,
        'User-Agent': shared_state.values["user_agent"]
    }

    try:
        response = requests.get(f"https://www.imdb.com/title/{imdb_id}/", headers=headers, timeout=10)
    except Exception as e:
        info(f"Error loading IMDb metadata for {imdb_id}: {e}")
        return localized_title

    try:
        match = re.findall(r'<title>(.*?) \(.*?</title>', response.text)
        localized_title = match[0]
    except:
        try:
            match = re.findall(r'<title>(.*?) - IMDb</title>', response.text)
            localized_title = match[0]
        except:
            pass

    if not localized_title:
        debug(f"Could not get localized title for {imdb_id} in {language} from IMDb")

    localized_title = html.unescape(localized_title)
    localized_title = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß&-']", ' ', localized_title).strip()
    localized_title = localized_title.replace(" - ", "-")
    localized_title = re.sub(r'\s{2,}', ' ', localized_title)

    return localized_title


def get_clean_title(title):
    try:
        extracted_title = re.findall(r"(.*?)(?:.(?!19|20)\d{2}|\.German|.GERMAN|\.\d{3,4}p|\.S(?:\d{1,3}))", title)[0]
        leftover_tags_removed = re.sub(
            r'(|.UNRATED.*|.Unrated.*|.Uncut.*|.UNCUT.*)(|.Directors.Cut.*|.Final.Cut.*|.DC.*|.REMASTERED.*|.EXTENDED.*|.Extended.*|.Theatrical.*|.THEATRICAL.*)',
            "", extracted_title)
        clean_title = leftover_tags_removed.replace(".", " ").strip().replace(" ", "+")

    except:
        clean_title = title
    return clean_title


def get_imdb_id_from_title(shared_state, title, language="de"):
    imdb_id = None

    if re.search(r"S\d{1,3}(E\d{1,3})?", title, re.IGNORECASE):
        ttype = "tv"
    else:
        ttype = "ft"

    title = get_clean_title(title)

    threshold = 60 * 60 * 48  # 48 hours
    context = "recents_imdb"
    recently_searched = shared_state.get_recently_searched(shared_state, context, threshold)
    if title in recently_searched:
        title_item = recently_searched[title]
        if title_item["timestamp"] > datetime.now() - timedelta(seconds=threshold):
            return title_item["imdb_id"]

    headers = {
        'Accept-Language': language,
        'User-Agent': shared_state.values["user_agent"]
    }

    results = requests.get(f"https://www.imdb.com/find/?q={quote(title)}&s=tt&ttype={ttype}&ref_=fn_{ttype}",
                           headers=headers, timeout=10)

    if results.status_code == 200:
        soup = BeautifulSoup(results.text, "html.parser")
        props = soup.find("script", text=re.compile("props"))
        details = loads(props.string)
        search_results = details['props']['pageProps']['titleResults']['results']

        if len(search_results) > 0:
            for result in search_results:
                try:
                    found_title = result["listItem"]["titleText"]
                    found_id = result["listItem"]["titleId"]
                except KeyError:
                    found_title = result["titleNameText"]
                    found_id = result['id']

                if shared_state.search_string_in_sanitized_title(title, found_title):
                    imdb_id = found_id
                    break
    else:
        debug(f"Request on IMDb failed: {results.status_code}")

    recently_searched[title] = {
        "imdb_id": imdb_id,
        "timestamp": datetime.now()
    }
    shared_state.update(context, recently_searched)

    if not imdb_id:
        debug(f"No IMDb-ID found for {title}")

    return imdb_id
