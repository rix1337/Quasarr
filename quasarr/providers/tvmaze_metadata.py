# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import requests

from quasarr.providers.log import info


def get_title_from_tvrage_id(tvrage_id):
    try:
        url = f"https://api.tvmaze.com/lookup/shows?tvrage={tvrage_id}"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            return data.get("name", "Title not found")
        else:
            info(f"Error: Unable to fetch title. HTTP Status Code: {response.status_code}")
            return ""
    except Exception as e:
        info(f"Exception occurred: {e}")
        return ""
