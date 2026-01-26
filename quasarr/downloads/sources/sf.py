# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.search.sources.sf import parse_mirrors

hostname = "sf"


def is_last_section_integer(url):
    last_section = url.rstrip("/").split("/")[-1]
    if last_section.isdigit() and len(last_section) <= 3:
        return int(last_section)
    return None


def resolve_sf_redirect(url, user_agent):
    """Follow redirects and return final URL or None if 404."""
    try:
        r = requests.get(
            url, allow_redirects=True, timeout=10, headers={"User-Agent": user_agent}
        )
        r.raise_for_status()
        if r.history:
            for resp in r.history:
                debug(f"Redirected from {resp.url} to {r.url}")
            if "/404.html" in r.url:
                info(f"SF link redirected to 404 page: {r.url}")
                return None
            return r.url
        else:
            info(
                f"SF blocked attempt to resolve {url}. Your IP may be banned. Try again later."
            )
    except Exception as e:
        info(f"Error fetching redirected URL for {url}: {e}")
        mark_hostname_issue(
            hostname, "download", str(e) if "e" in dir() else "Download error"
        )
    return None


def get_sf_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    SF source handler - resolves redirects and returns filecrypt links.
    """

    sf = shared_state.values["config"]("Hostnames").get("sf")
    user_agent = shared_state.values["user_agent"]

    # Handle external redirect URLs
    if url.startswith(f"https://{sf}/external"):
        resolved_url = resolve_sf_redirect(url, user_agent)
        if not resolved_url:
            return {"links": [], "imdb_id": None}
        return {"links": [[resolved_url, "filecrypt"]], "imdb_id": None}

    # Handle series page URLs - need to find the right release
    release_pattern = re.compile(
        r"""
          ^                                   
          (?P<name>.+?)\.                     
          S(?P<season>\d+)                    
          (?:E\d+(?:-E\d+)?)?                 
          \.                                  
          .*?\.                               
          (?P<resolution>\d+p)                
          \..+?                               
          -(?P<group>\w+)                     
          $                                   
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    release_match = release_pattern.match(title)
    if not release_match:
        return {"links": [], "imdb_id": None}

    release_parts = release_match.groupdict()

    season = is_last_section_integer(url)
    try:
        if not season:
            season = "ALL"

        headers = {"User-Agent": user_agent}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        series_page = r.text
        soup = BeautifulSoup(series_page, "html.parser")

        # Extract IMDb id if present
        imdb_id = None
        a_imdb = soup.find("a", href=re.compile(r"imdb\.com/title/tt\d+"))
        if a_imdb:
            m = re.search(r"(tt\d+)", a_imdb["href"])
            if m:
                imdb_id = m.group(1)
                debug(f"Found IMDb id: {imdb_id}")

        season_id = re.findall(r"initSeason\('(.+?)\',", series_page)[0]
        epoch = str(datetime.now().timestamp()).replace(".", "")[:-3]
        api_url = (
            "https://"
            + sf
            + "/api/v1/"
            + season_id
            + f"/season/{season}?lang=ALL&_="
            + epoch
        )

        r = requests.get(api_url, headers=headers, timeout=10)
        r.raise_for_status()
        try:
            data = r.json()["html"]
        except ValueError:
            epoch = str(datetime.now().timestamp()).replace(".", "")[:-3]
            api_url = (
                "https://"
                + sf
                + "/api/v1/"
                + season_id
                + f"/season/ALL?lang=ALL&_="
                + epoch
            )
            r = requests.get(api_url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()["html"]

        content = BeautifulSoup(data, "html.parser")
        items = content.find_all("h3")

        for item in items:
            try:
                details = item.parent.parent.parent
                name = details.find("small").text.strip()

                result_pattern = re.compile(
                    r"^(?P<name>.+?)\.S(?P<season>\d+)(?:E\d+)?\..*?(?P<resolution>\d+p)\..+?-(?P<group>[\w/-]+)$",
                    re.IGNORECASE,
                )
                result_match = result_pattern.match(name)

                if not result_match:
                    continue

                result_parts = result_match.groupdict()

                name_match = (
                    release_parts["name"].lower() == result_parts["name"].lower()
                )
                season_match = release_parts["season"] == result_parts["season"]
                resolution_match = (
                    release_parts["resolution"].lower()
                    == result_parts["resolution"].lower()
                )

                result_groups = {g.lower() for g in result_parts["group"].split("/")}
                release_groups = {g.lower() for g in release_parts["group"].split("/")}
                group_match = not result_groups.isdisjoint(release_groups)

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

                    real_url = resolve_sf_redirect(release_url, user_agent)
                    if real_url:
                        # Use the mirror name if we have it, otherwise use "filecrypt"
                        mirror_name = mirror if mirror else "filecrypt"
                        return {"links": [[real_url, mirror_name]], "imdb_id": imdb_id}
                    else:
                        return {"links": [], "imdb_id": imdb_id}
            except:
                continue
    except:
        pass

    return {"links": [], "imdb_id": None}
