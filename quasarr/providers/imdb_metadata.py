# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

import requests


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

    if not localized_title:
        print(f"Could not get localized title for {imdb_id} in {language} from IMDb")

    return localized_title
