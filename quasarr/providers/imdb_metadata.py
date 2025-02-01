# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests
from bs4 import BeautifulSoup


def get_poster_link(shared_state, imdb_id):
    poster_link = None
    if imdb_id:
        headers = {'User-Agent': shared_state.values["user_agent"]}
        request = requests.get(f"https://www.imdb.com/title/{imdb_id}/", headers=headers).text
        soup = BeautifulSoup(request, "html.parser")
        try:
            poster_set = soup.find('div', class_='ipc-poster').div.img[
                "srcset"]  # contains links to posters in ascending resolution
            poster_links = [x for x in poster_set.split(" ") if
                            len(x) > 10]  # extract all poster links ignoring resolution info
            poster_link = poster_links[-1]  # get the highest resolution poster
        except:
            pass

    if not poster_link and shared_state.debug():
        print(f"Could not get poster title for {imdb_id} from IMDb")

    return poster_link


def get_localized_title(shared_state, imdb_id, language='de'):
    localized_title = None

    headers = {
        'Accept-Language': language,
        'User-Agent': shared_state.values["user_agent"]
    }

    try:
        response = requests.get(f"https://www.imdb.com/title/{imdb_id}/", headers=headers)
    except Exception as e:
        print(f"Error loading IMDb metadata for {imdb_id}: {e}")
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

    if not localized_title and shared_state.debug():
        print(f"Could not get localized title for {imdb_id} in {language} from IMDb")

    return localized_title
