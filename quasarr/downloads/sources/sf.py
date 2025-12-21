# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug
from quasarr.search.sources.sf import parse_mirrors


def is_last_section_integer(url):
    last_section = url.rstrip('/').split('/')[-1]
    if last_section.isdigit() and len(last_section) <= 3:
        return int(last_section)
    return None


def get_sf_download_links(shared_state, url, mirror, title):  # signature must align with other download link functions!
    release_pattern = re.compile(
        r'''
          ^                                   # start of string
          (?P<name>.+?)\.                     # show name (dots in name) up to the dot before “S”
          S(?P<season>\d+)                    # “S” + season number
          (?:E\d+(?:-E\d+)?)?                 # optional “E##” or “E##-E##”
          \.                                  # literal dot
          .*?\.                               # anything (e.g. language/codec) up to next dot
          (?P<resolution>\d+p)                # resolution “720p”, “1080p”, etc.
          \..+?                               # dot + more junk (e.g. “.WEB.h264”)
          -(?P<group>\w+)                     # dash + release group at end
          $                                   # end of string
        ''',
        re.IGNORECASE | re.VERBOSE
    )

    release_match = release_pattern.match(title)

    if not release_match:
        return {
            "real_url": None,
            "imdb_id": None,
        }

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

        soup = BeautifulSoup(series_page, "html.parser")
        # extract IMDb id if present
        imdb_id = None
        a_imdb = soup.find("a", href=re.compile(r"imdb\.com/title/tt\d+"))
        if a_imdb:
            m = re.search(r"(tt\d+)", a_imdb["href"])
            if m:
                imdb_id = m.group(1)
                debug(f"Found IMDb id: {imdb_id}")

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

                    mirrors = parse_mirrors(f"https://{sf}", details)

                    if mirror:
                        if mirror not in mirrors["season"]:
                            continue
                        release_url = mirrors["season"][mirror]
                        if not release_url:
                            info(f"Could not find mirror '{mirror}' for '{title}'")
                    else:
                        release_url = next(iter(mirrors["season"].values()))

                    real_url = resolve_sf_redirect(release_url, shared_state.values["user_agent"])
                    return {
                        "real_url": real_url,
                        "imdb_id": imdb_id,
                    }
            except:
                continue
    except:
        pass

    return {
        "real_url": None,
        "imdb_id": None,
    }


def resolve_sf_redirect(url, user_agent):
    try:
        response = requests.get(url, allow_redirects=True, timeout=10,
                                headers={'User-Agent': user_agent})
        if response.history:
            for resp in response.history:
                debug(f"Redirected from {resp.url} to {response.url}")
            if "/404.html" in response.url:
                info(f"SF link redirected to 404 page: {response.url}")
                return None
            return response.url
        else:
            info(f"SF blocked attempt to resolve {url}. Your IP may be banned. Try again later.")
    except Exception as e:
        info(f"Error fetching redirected URL for {url}: {e}")
    return None
