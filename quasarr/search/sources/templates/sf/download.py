# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.mirror_filters import link_priority_rank, mirror_allowed
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.downloads.sources.helpers.redirect import resolve_crypter_redirect
from quasarr.providers.cloudflare import LazyFlareSolverrSession
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info, warn
from quasarr.search.sources.templates import site_url


class Source(AbstractDownloadSource):
    initials = "sf"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        cf_session = LazyFlareSolverrSession(shared_state)
        try:
            return self._get_download_links(
                shared_state, url, mirrors, title, password, cf_session
            )
        finally:
            cf_session.close()

    def _get_download_links(
        self, shared_state, url, mirrors, title, password, cf_session
    ):
        """
        SF source handler - resolves redirects and returns filecrypt links.
        """
        sf = shared_state.values["config"]("Hostnames").get(Source.initials)
        user_agent = shared_state.values["user_agent"]

        # Handle external redirect URLs
        if url.startswith(f"https://{sf}/external"):
            resolved_url = _resolve_sf_redirect(url, user_agent, cf_session)
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

        season = _is_last_section_integer(url)
        try:
            if not season:
                season = "ALL"

            headers = {"User-Agent": user_agent}
            r = cf_session.get(
                url,
                headers,
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                request_get=requests.get,
            )
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
            api_url = site_url(
                shared_state,
                Source.initials,
                "api_season",
                season_id=season_id,
                season=season,
                epoch=epoch,
            )

            r = cf_session.get(
                api_url,
                headers,
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                request_get=requests.get,
            )
            r.raise_for_status()
            try:
                data = r.json()["html"]
            except ValueError:
                epoch = str(datetime.now().timestamp()).replace(".", "")[:-3]
                api_url = site_url(
                    shared_state,
                    Source.initials,
                    "api_season",
                    season_id=season_id,
                    season="ALL",
                    epoch=epoch,
                )
                r = cf_session.get(
                    api_url,
                    headers,
                    DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                    request_get=requests.get,
                )
                r.raise_for_status()
                data = r.json()["html"]

            content = BeautifulSoup(data, "html.parser")
            # An episode grabbed from a season entry carries SxxEyy only in its title.
            season_title = re.sub(
                r"(S\d+)E\d+(?:-E\d+)?", r"\1", title, flags=re.IGNORECASE
            ).lower()
            episode_match = re.search(r"S\d+E(\d+)", title, re.IGNORECASE)

            release = None
            for item in content.find_all("h3"):
                try:
                    details = item.parent.parent.parent
                    name = details.find("small").text.strip()
                    if not _release_matches(name, release_parts):
                        continue
                    if name.lower() == season_title:
                        release = (name, details)
                        break
                    release = release or (name, details)
                except Exception:
                    continue

            if not release:
                return {"links": [], "imdb_id": None}

            name, details = release
            info(f'Release "{name}" found at: {url}')
            mirrors_dict = _parse_mirrors(f"https://{sf}", details)
            links = mirrors_dict.get("season", {})
            if episode_match and not re.search(r"S\d+E\d+", name, re.IGNORECASE):
                episode = next(
                    (
                        e
                        for e in mirrors_dict.get("episodes", [])
                        if e["number"] == int(episode_match.group(1))
                    ),
                    None,
                )
                if episode and episode["links"]:
                    links = episode["links"]

            selected = _select_mirrors(links, mirrors)
            if not selected:
                info(f"Could not find any of mirrors '{mirrors}' for '{title}'")
                return {"links": [], "imdb_id": imdb_id}

            resolved = []
            for release_url, mirror_name in selected:
                real_url = _resolve_sf_redirect(release_url, user_agent, cf_session)
                if real_url:
                    resolved.append([real_url, mirror_name])
            return {"links": resolved, "imdb_id": imdb_id}
        except Exception as e:
            mark_hostname_issue(Source.initials, "download", str(e))

        return {"links": [], "imdb_id": None}


def _release_matches(name, release_parts):
    match = re.match(
        r"^(?P<name>.+?)\.S(?P<season>\d+)(?:E\d+)?\..*?(?P<resolution>\d+p)\..+?-(?P<group>[\w/-]+)$",
        name,
        re.IGNORECASE,
    )
    if not match:
        return False
    parts = match.groupdict()
    return (
        release_parts["name"].lower() == parts["name"].lower()
        and release_parts["season"] == parts["season"]
        and release_parts["resolution"].lower() == parts["resolution"].lower()
        and not {g.lower() for g in parts["group"].split("/")}.isdisjoint(
            g.lower() for g in release_parts["group"].split("/")
        )
    )


def _select_mirrors(links, mirrors):
    """Every allowed mirror's link, whitelisted ones first in category priority order."""
    ranked = sorted(
        (
            (link_priority_rank([link, name], mirrors), link, name.lower())
            for name, link in links.items()
        ),
        key=lambda item: item[0],
    )
    return [(link, name) for _, link, name in ranked if mirror_allowed(name, mirrors)]


def _parse_mirrors(base_url, entry):
    """
    Parse season and episode mirror links from an SF release entry.
    """
    mirrors = {}
    try:
        host_map = {
            "1F": "1fichier",
            "DD": "ddownload",
            "KA": "katfile",
            "RG": "rapidgator",
            "TB": "turbobit",
        }

        h3 = entry.select_one("h3")
        name = h3.get_text(separator=" ", strip=True) if h3 else ""

        season = {}
        for anchor in entry.select("a.dlb.row"):
            if anchor.find_parent("div.list.simple"):
                continue
            host = anchor.get_text(strip=True)
            if len(host) > 2:
                season[host] = f"{base_url}{anchor['href']}"

        if not season:
            fallback = next(
                (
                    anchor
                    for anchor in entry.select("a.dlb.row")
                    if not anchor.find_parent("div.list.simple")
                ),
                None,
            )
            if fallback:
                season["filecrypt"] = f"{base_url}{fallback['href']}"

        episodes = []
        for episode_row in entry.select("div.list.simple > div.row"):
            if "head" in episode_row.get("class", []):
                continue

            columns = episode_row.find_all("div", recursive=False)
            number = int(columns[0].get_text(strip=True).rstrip("."))
            title = columns[1].get_text(strip=True)

            episode_links = {}
            for anchor in episode_row.select("div.row > a.dlb.row"):
                host = anchor.get_text(strip=True)
                full_host = host_map.get(host, host)
                episode_links[full_host] = f"{base_url}{anchor['href']}"

            episodes.append({"number": number, "title": title, "links": episode_links})

        mirrors = {"name": name, "season": season, "episodes": episodes}
    except Exception as e:
        warn(f"Error parsing mirrors: {e}")
        mark_hostname_issue(
            Source.initials, "download", str(e) if "e" in dir() else "Download error"
        )

    return mirrors


def _is_last_section_integer(url):
    last_section = url.rstrip("/").split("/")[-1]
    if last_section.isdigit() and len(last_section) <= 3:
        return int(last_section)
    return None


def _resolve_sf_redirect(url, user_agent, cf_session):
    """Resolve manually until blocked, then let the shared browser session follow.

    SF only publishes crypter containers, so off-site final URLs are not accepted.
    """
    return resolve_crypter_redirect(
        url, user_agent, cf_session, Source.initials, accept_offsite=False
    )
