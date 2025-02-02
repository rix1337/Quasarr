# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info


def is_last_section_integer(url):
    last_section = url.rstrip('/').split('/')[-1]
    if last_section.isdigit() and len(last_section) <= 3:
        return int(last_section)
    return None


def get_release_url(url, title, shared_state):
    release_pattern = re.compile(
        r'^(?P<name>.+?)\.S(?P<season>\d+)(?:E\d+)?\..*?\.(?P<resolution>\d+p)\..+?-(?P<group>\w+)$', re.IGNORECASE)
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

        series_page = requests.get(url, headers=headers, timeout=10).text
        season_id = re.findall(r"initSeason\('(.+?)\',", series_page)[0]
        epoch = str(datetime.now().timestamp()).replace('.', '')[:-3]
        api_url = 'https://' + sf + '/api/v1/' + season_id + f'/season/{season}?lang=ALL&_=' + epoch

        response = requests.get(api_url, headers=headers, timeout=10)
        try:
            data = response.json()["html"]
        except ValueError:
            epoch = str(datetime.now().timestamp()).replace('.', '')[:-3]
            api_url = 'https://' + sf + '/api/v1/' + season_id + f'/season/ALL?lang=ALL&_=' + epoch
            response = requests.get(api_url, headers=headers, timeout=10)
            data = response.json()["html"]

        content = BeautifulSoup(data, "html.parser")

        items = content.find_all("h3")

        for item in items:
            try:
                details = item.parent.parent.parent
                name = details.find("small").text.strip()

                result_pattern = re.compile(
                    r'^(?P<name>.+?)\.S(?P<season>\d+)(?:E\d+)?\..*?(?P<resolution>\d+p)\..+?-(?P<group>[\w/-]+)$',
                    re.IGNORECASE
                )
                result_match = result_pattern.match(name)

                if not result_match:
                    continue

                result_parts = result_match.groupdict()

                # Normalize all relevant fields for case-insensitive comparison
                name_match = release_parts['name'].lower() == result_parts['name'].lower()
                season_match = release_parts['season'] == result_parts['season']  # Numbers are case-insensitive
                resolution_match = release_parts['resolution'].lower() == result_parts['resolution'].lower()

                # Handle multiple groups and case-insensitive matching
                result_groups = {g.lower() for g in result_parts['group'].split('/')}
                release_groups = {g.lower() for g in release_parts['group'].split('/')}
                group_match = not result_groups.isdisjoint(release_groups)  # Checks if any group matches

                if name_match and season_match and resolution_match and group_match:
                    info(f'Release "{name}" found on SF at: {url}')
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
        response = requests.get(url, allow_redirects=True, timeout=10)
        return response.url
    except Exception as e:
        info(f"Error fetching redirected URL for {url}: {e}")
        return None
