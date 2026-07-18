# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import uuid
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.cloudflare import (
    flaresolverr_create_session,
    flaresolverr_destroy_session,
    flaresolverr_get,
    is_cloudflare_challenge,
)
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import detect_crypter_type, is_flaresolverr_available


class Source(AbstractDownloadSource):
    initials = "wd"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        WD source handler - resolves redirects and returns protected download links.
        """
        wd = shared_state.values["config"]("Hostnames").get(Source.initials)

        # Try normal request first
        text = None
        status_code = None
        session_id = None

        try:
            headers = {"User-Agent": shared_state.values["user_agent"]}
            r = requests.get(
                url,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            # Don't raise for status yet, check for 403/challenge
            if r.status_code == 403 or is_cloudflare_challenge(r.text):
                raise requests.RequestException("Cloudflare protection detected")
            r.raise_for_status()
            text = r.text
            status_code = r.status_code
        except Exception as e:
            # If blocked or failed, try FlareSolverr
            if is_flaresolverr_available(shared_state):
                debug("Encountered Cloudflare on download. Trying FlareSolverr...")
                # Create a temporary FlareSolverr session for this download attempt
                session_id = str(uuid.uuid4())
                created_session = flaresolverr_create_session(shared_state, session_id)
                if not created_session:
                    info(
                        "Could not create FlareSolverr session. Proceeding without session..."
                    )
                    session_id = None
                else:
                    debug(f"Created FlareSolverr session: {session_id}")

                try:
                    r = flaresolverr_get(
                        shared_state,
                        url,
                        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                        session_id=session_id,
                    )
                    if r.status_code == 403 or is_cloudflare_challenge(r.text):
                        info(
                            "Could not bypass Cloudflare protection with FlareSolverr!"
                        )
                        mark_hostname_issue(
                            Source.initials, "download", "Cloudflare challenge failed"
                        )
                        if session_id:
                            flaresolverr_destroy_session(shared_state, session_id)
                        return {"links": [], "imdb_id": None}
                    text = r.text
                    status_code = r.status_code
                except RuntimeError as fs_err:
                    info(f"Access failed via FlareSolverr: {fs_err}")
                    if session_id:
                        flaresolverr_destroy_session(shared_state, session_id)
                    return {"links": [], "imdb_id": None}
            else:
                info(
                    f"Site has been updated or is protected. "
                    f"Grabbing download links for {title} not possible! ({e})"
                )
                mark_hostname_issue(Source.initials, "download", str(e))
                return {"links": [], "imdb_id": None}

        try:
            if status_code and status_code >= 400:
                mark_hostname_issue(
                    Source.initials, "download", f"Download error: {str(status_code)}"
                )

            soup = BeautifulSoup(text, "html.parser")

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
                    "Downloads section not found. "
                    f"Grabbing download links for {title} not possible!"
                )
                return {"links": [], "imdb_id": None}

            card = header.find_parent("div", class_="card")
            body = card.find("div", class_="card-body")
            link_tags = body.find_all(
                "a", href=True, class_=lambda c: c and "background-" in c
            )

            results = []
            try:
                for a in link_tags:
                    raw_href = a["href"]
                    full_link = urljoin(f"https://{wd}", raw_href)

                    # resolve any redirects using the same session (or requests if no session)
                    resolved = _resolve_wd_redirect(
                        shared_state, full_link, session_id=session_id
                    )

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

                        if mirrors and not any(
                            m.lower() in hoster.lower() for m in mirrors
                        ):
                            debug(
                                f'Skipping link from "{hoster}" (not in desired mirrors "{mirrors}")!'
                            )
                            continue

                        results.append([resolved, hoster])
            except Exception as e:
                info(
                    "Site has been updated. "
                    f"Parsing download links for {title} not possible! Error: {e}"
                )

            return {
                "links": results,
                "imdb_id": imdb_id,
            }

        except Exception as e:
            info(
                "Site has been updated. "
                f"Grabbing download links for {title} not possible! Error: {e}"
            )
            return {"links": [], "imdb_id": None}
        finally:
            # Always destroy the session if we created one
            if session_id:
                debug(f"Destroying FlareSolverr session: {session_id}")
                flaresolverr_destroy_session(shared_state, session_id)


def _resolve_wd_redirect(shared_state, url, session_id=None):
    """
    Follow redirects for a WD mirror URL and return the final destination.
    """
    # Try FlareSolverr first if available and session_id is provided
    if session_id and is_flaresolverr_available(shared_state):
        try:
            r = flaresolverr_get(
                shared_state,
                url,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                session_id=session_id,
                protect_filecrypt_redirects=True,
            )
            if r.url.endswith("/404.html"):
                return None
            if detect_crypter_type(r.url) == "filecrypt":
                return r.url
            if r.status_code == 200 and r.url != url:
                return r.url
            info(f"Blocked attempt to resolve {url}. Status: {r.status_code}")
        except Exception as e:
            info(f"FlareSolverr error fetching redirected URL for {url}: {e}")
            # Fallback to requests if FlareSolverr fails?
            # For now, let's assume if FS is configured we should rely on it or fail.
            # But the user asked to reconsider "without cloudflare".

    # Fallback to regular requests if FlareSolverr not used or failed/not configured
    try:
        user_agent = shared_state.values["user_agent"]
        current_url = url
        visited = set()
        session = requests.Session()

        for _hop in range(8):
            if current_url in visited:
                debug(f"WD redirect loop detected for {current_url}")
                return None
            visited.add(current_url)

            if detect_crypter_type(current_url) is not None:
                return current_url

            r = session.get(
                current_url,
                allow_redirects=False,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": user_agent},
            )

            location = (r.headers.get("Location") or "").strip()
            if location:
                next_url = urljoin(current_url, location)
                debug(f"Redirected from {current_url} to {next_url}")
                if next_url.endswith("/404.html"):
                    return None
                current_url = next_url
                continue

            final_url = (r.url or current_url).strip()
            if final_url.endswith("/404.html"):
                return None
            if detect_crypter_type(final_url) == "filecrypt":
                return final_url
            if r.status_code >= 400:
                info(f"Blocked attempt to resolve {url}. Status: {r.status_code}")
                return None
            info(
                f"Blocked attempt to resolve {url}. "
                "Your IP may be banned. Try again later."
            )
            return None
    except Exception as e:
        info(f"Error fetching redirected URL for {url}: {e}")
        mark_hostname_issue(
            Source.initials, "download", str(e) if "e" in dir() else "Download error"
        )
    return None
