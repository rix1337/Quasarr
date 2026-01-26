# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.providers.cloudflare import flaresolverr_get, is_cloudflare_challenge
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import is_flaresolverr_available

hostname = "wd"


def resolve_wd_redirect(url, user_agent):
    """
    Follow redirects for a WD mirror URL and return the final destination.
    """
    try:
        r = requests.get(
            url,
            allow_redirects=True,
            timeout=10,
            headers={"User-Agent": user_agent},
        )
        r.raise_for_status()
        if r.history:
            for resp in r.history:
                debug(f"Redirected from {resp.url} to {r.url}")
            return r.url
        else:
            info(
                f"WD blocked attempt to resolve {url}. Your IP may be banned. Try again later."
            )
    except Exception as e:
        info(f"Error fetching redirected URL for {url}: {e}")
        mark_hostname_issue(
            hostname, "download", str(e) if "e" in dir() else "Download error"
        )
    return None


def get_wd_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    WD source handler - resolves redirects and returns protected download links.
    """

    wd = shared_state.values["config"]("Hostnames").get("wd")
    user_agent = shared_state.values["user_agent"]

    try:
        r = requests.get(url)
        if r.status_code >= 400 or is_cloudflare_challenge(r.text):
            if is_flaresolverr_available(shared_state):
                info(
                    "WD is protected by Cloudflare. Using FlareSolverr to bypass protection."
                )
                r = flaresolverr_get(shared_state, url)
            else:
                info(
                    "WD is protected by Cloudflare but FlareSolverr is not configured. "
                    "Please configure FlareSolverr in the web UI to access this site."
                )
                mark_hostname_issue(
                    hostname, "download", "FlareSolverr required but missing."
                )
                return {"links": [], "imdb_id": None}

        if r.status_code >= 400:
            mark_hostname_issue(
                hostname, "download", f"Download error: {str(r.status_code)}"
            )

        soup = BeautifulSoup(r.text, "html.parser")

        # extract IMDb id if present
        imdb_id = None
        a_imdb = soup.find("a", href=re.compile(r"imdb\.com/title/tt\d+"))
        if a_imdb:
            m = re.search(r"(tt\d+)", a_imdb["href"])
            if m:
                imdb_id = m.group(1)
                debug(f"Found IMDb id: {imdb_id}")

        # find Downloads card
        header = soup.find(
            "div",
            class_="card-header",
            string=re.compile(r"^\s*Downloads\s*$", re.IGNORECASE),
        )
        if not header:
            info(
                f"WD Downloads section not found. Grabbing download links for {title} not possible!"
            )
            return {"links": [], "imdb_id": None}

        card = header.find_parent("div", class_="card")
        body = card.find("div", class_="card-body")
        link_tags = body.find_all(
            "a", href=True, class_=lambda c: c and "background-" in c
        )
    except RuntimeError as e:
        # Catch FlareSolverr not configured error
        info(f"WD access failed: {e}")
        return {"links": [], "imdb_id": None}
    except Exception:
        info(
            f"WD site has been updated. Grabbing download links for {title} not possible!"
        )
        return {"links": [], "imdb_id": None}

    results = []
    try:
        for a in link_tags:
            raw_href = a["href"]
            full_link = urljoin(f"https://{wd}", raw_href)

            # resolve any redirects
            resolved = resolve_wd_redirect(full_link, user_agent)

            if resolved:
                if resolved.endswith("/404.html"):
                    info(f"Link {resolved} is dead!")
                    continue

                # determine hoster
                hoster = a.get_text(strip=True) or None
                if not hoster:
                    for cls in a.get("class", []):
                        if cls.startswith("background-"):
                            hoster = cls.split("-", 1)[1]
                            break

                if mirror and mirror.lower() not in hoster.lower():
                    debug(
                        f'Skipping link from "{hoster}" (not the desired mirror "{mirror}")!'
                    )
                    continue

                results.append([resolved, hoster])
    except Exception:
        info(
            f"WD site has been updated. Parsing download links for {title} not possible!"
        )

    return {
        "links": results,
        "imdb_id": imdb_id,
    }
