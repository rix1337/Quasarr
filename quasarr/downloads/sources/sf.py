# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup


def is_last_section_integer(url):
    last_section = url.rstrip('/').split('/')[-1]
    if last_section.isdigit() and len(last_section) <= 3:
        return int(last_section)
    return None


def get_release_url(url, title, shared_state):
    release_pattern = re.compile(
        r'^(?P<name>.+?)\.S(?P<season>\d+)(?:E\d+)?\..*?\.(?P<resolution>\d+p)\..+?-(?P<group>\w+)$')
    release_match = release_pattern.match(title)

    if not release_match:
        return None

    release_parts = release_match.groupdict()

    season = is_last_section_integer(url)
    try:
        if not season:
            season = "ALL"

        sf = shared_state.values["config"]("Hostnames").get("sf")
        headers = {
            'User-Agent': shared_state.values["user_agent"],
        }

        series_page = requests.get(url, headers).text
        season_id = re.findall(r"initSeason\('(.+?)\',", series_page)[0]
        epoch = str(datetime.now().timestamp()).replace('.', '')[:-3]
        api_url = 'https://' + sf + '/api/v1/' + season_id + f'/season/{season}?lang=ALL&_=' + epoch

        response = requests.get(api_url)
        data = response.json()["html"]
        content = BeautifulSoup(data, "html.parser")

        items = content.find_all("h3")

        for item in items:
            try:
                details = item.parent.parent.parent
                name = details.find("small").text.strip()

                result_pattern = re.compile(
                    r'^(?P<name>.+?)\.S(?P<season>\d+)\..*?(?P<resolution>\d+p)\..+?[-/](?P<group>\w+)(?:[-/]\w+)?$')
                result_match = result_pattern.match(name)

                if not result_match:
                    continue

                result_parts = result_match.groupdict()

                if (release_parts['name'] == result_parts['name'] and
                        release_parts['season'] == result_parts['season'] and
                        release_parts['resolution'] == result_parts['resolution'] and
                        release_parts['group'] == result_parts['group']):
                    print(f'Release "{name}" found on SF at: {url}')
                    release_url = f'https://{sf}{details.find("a")["href"]}'
                    real_url = resolve_sf_redirect(release_url)
                    return real_url
            except:
                continue
    except:
        pass

    return None


def resolve_sf_redirect(url):
    try:
        response = requests.get(url, allow_redirects=True)
        return response.url
    except Exception as e:
        print(f"Error fetching redirected URL for {url}: {e}")
        return None
