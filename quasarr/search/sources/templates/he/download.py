# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import uuid
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.cloudflare import (
    flaresolverr_create_session,
    flaresolverr_destroy_session,
    flaresolverr_get,
    flaresolverr_post,
    is_cloudflare_challenge,
)
from quasarr.providers.log import debug, info, warn
from quasarr.providers.utils import is_flaresolverr_available


class Source(AbstractDownloadSource):
    initials = "he"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        HE source handler - fetches plain download links from HE pages.
        """
        headers = {
            "User-Agent": shared_state.values["user_agent"],
        }

        # 1. Try Standard Strategy (Fast)
        result = _strategy_standard(url, headers)

        # 2. If Standard failed (result is None), switch to FlareSolverr (Robust)
        if result is None or result.get("inconclusive"):
            inconclusive_result = result
            if (
                result
                and result.get("inconclusive")
                and not is_flaresolverr_available(shared_state)
            ):
                info("FlareSolverr unavailable after inconclusive HE form response.")
                return _protected_release_result(url, result["imdb_id"])
            info("Standard connection failed/blocked. Switching to FlareSolverr...")
            result = _strategy_flaresolverr_loop(shared_state, url)
            if (
                inconclusive_result
                and inconclusive_result.get("inconclusive")
                and (not result or not result.get("links"))
            ):
                info("FlareSolverr could not complete inconclusive HE form response.")
                return _protected_release_result(url, inconclusive_result["imdb_id"])

        requested_mirrors = {
            _normalize_mirror_name(mirror) for mirror in (mirrors or []) if mirror
        }
        if result and result.get("links") and not result.get("protected"):
            result["links"] = _filter_links_by_mirrors(
                result["links"], requested_mirrors
            )

        if result and result.get("protected"):
            info(f"CAPTCHA required to unlock external download links for {title}")
            return result

        if not result or not result["links"]:
            info(f"No external download links found for {title}")
            return {"links": [], "imdb_id": result["imdb_id"] if result else None}

        return result


def _normalize_mirror_name(mirror_name):
    normalized = mirror_name.lower().strip()

    if "://" in normalized:
        parsed = urlparse(normalized)
        normalized = parsed.netloc or parsed.path

    if normalized.startswith("www."):
        normalized = normalized[4:]

    normalized = normalized.split("/", 1)[0]
    normalized = normalized.split(":", 1)[0]
    if " " in normalized:
        normalized = normalized.split()[-1]
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]

    aliases = {
        "ddl": "ddownload",
        "ddlto": "ddownload",
        "rg": "rapidgator",
        "tb": "turbobit",
    }
    return aliases.get(normalized, normalized)


def _filter_links_by_mirrors(links, requested_mirrors):
    if not requested_mirrors:
        return links

    filtered_links = []
    for link_url, mirror_name in links:
        if _normalize_mirror_name(mirror_name) in requested_mirrors:
            filtered_links.append([link_url, mirror_name])
    return filtered_links


def _remove_fragment(url):
    """Removes #unlocked or other fragments from URL."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def _extract_imdb_id(html_content):
    """Helper to extract IMDB ID from HTML content."""
    if not html_content:
        return None
    try:
        # Avoid full parsing if possible for speed, but BS4 is safer
        soup = BeautifulSoup(html_content, "html.parser")
        imdb_link = soup.find(
            "a", href=re.compile(r"imdb\.com/title/tt\d+", re.IGNORECASE)
        )
        if imdb_link:
            href = imdb_link["href"].strip()
            m = re.search(r"(tt\d{4,7})", href)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def _extract_form_payload_list(html_content, url):
    """
    Extracts form data as a LIST of TUPLES from raw HTML.
    Crucial for sites that require duplicate keys (e.g. maZQ-D).
    Returns: (action_url, payload_list_of_tuples, form_found_bool)
    """
    if not html_content:
        return None, [], False

    soup = BeautifulSoup(html_content, "html.parser")
    form = soup.find("form", id=re.compile(r"content-protector-access-form"))

    if not form:
        return None, [], False

    # 1. Action URL
    action = form.get("action") or url
    if not action.startswith("http"):
        action_url = urljoin(url, action)
    else:
        action_url = action

    action_url = _remove_fragment(action_url)

    # Use a LIST to preserve duplicate keys
    payload_list = []

    # 2. Standard Inputs
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        val = inp.get("value", "")
        payload_list.append((name, val))

    # 3. JS Injected Variables
    # Regex 1: append('<input name="key" value="val">')
    input_patt = re.compile(
        r"append\s*\(\s*['\"]<input\s+[^>]*?name=['\"](?P<key>[^'\"]+)['\"][^>]*?value=['\"](?P<val>[^'\"]+)['\"]",
        re.IGNORECASE,
    )
    # Regex 2: append('key', 'val')
    simple_patt = re.compile(
        r"append\s*\(\s*['\"](?P<key>[^\'\"]+)[\'\"]\s*,\s*['\"](?P<val>[^\'\"]+)[\'\"]\s*\)",
        re.IGNORECASE,
    )

    for script in soup.find_all("script"):
        txt = script.string or script.get_text()
        if not txt:
            continue

        for m in input_patt.finditer(txt):
            k, v = m.group("key"), m.group("val")
            payload_list.append((k, v))

        for m in simple_patt.finditer(txt):
            k, v = m.group("key"), m.group("val")
            payload_list.append((k, v))

    return action_url, payload_list, True


def _requires_manual_captcha(html_content):
    if not html_content:
        return False

    soup = BeautifulSoup(html_content, "html.parser")
    form = soup.find("form", id=re.compile(r"content-protector-access-form"))
    if not form:
        return False

    captcha_mode = form.find(
        "input",
        attrs={"name": "content-protector-captcha", "value": "1"},
    )
    captcha_id = form.find("input", attrs={"name": "captcha_id"})
    return bool(
        captcha_mode and captcha_id and str(captcha_id.get("value", "")).strip()
    )


def _protected_release_result(url, imdb_id):
    return {
        "links": [[_remove_fragment(url), Source.initials]],
        "imdb_id": imdb_id,
        "protected": True,
    }


def _parse_links_strict(html):
    """
    Parses links specifically from the content-protector-access-form div
    or the #unlocked div.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    anchors = []

    # Priority 1: .content-protector-access-form
    unlocked_forms = soup.select(".content-protector-access-form")
    for u in unlocked_forms:
        anchors.extend(u.find_all("a", href=True))

    # Priority 2: #unlocked div
    unlocked_div = soup.find("div", id="unlocked")
    if unlocked_div:
        anchors.extend(unlocked_div.find_all("a", href=True))

    valid_links = []
    for a in anchors:
        try:
            href = a["href"].strip()
            if not href.startswith("http"):
                continue

            netloc = urlparse(href).netloc.lower()
            hoster = netloc.split(":")[0]
            parts = hoster.split(".")
            if len(parts) >= 2:
                hoster = parts[-2]

            valid_links.append([href, hoster])
        except Exception:
            continue

    return valid_links


def _strategy_standard(url, headers):
    """
    Fast Path: Uses standard requests.
    Returns dict {'links': [], 'imdb_id': ...} if successful,
    or None if blocked/failed.
    """
    debug(f"Attempting Standard Strategy (No FlareSolverr) for {url}")
    session = requests.Session()
    clean_url = _remove_fragment(url)

    try:
        # 1. GET
        r = session.get(
            clean_url,
            headers=headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        if r.status_code == 403 or is_cloudflare_challenge(r.text):
            debug("Standard GET hit Cloudflare/403.")
            return None
        r.raise_for_status()

        # Extract IMDB immediately from the page content
        imdb_id = _extract_imdb_id(r.text)

        # Check immediate links
        links = _parse_links_strict(r.text)
        if links:
            debug(f"Standard: Found {len(links)} links immediately.")
            return {"links": links, "imdb_id": imdb_id}

        if _requires_manual_captcha(r.text):
            debug("Standard: Manual CAPTCHA required.")
            return _protected_release_result(clean_url, imdb_id)

        # 2. Extract Form
        action_url, payload_list, found_form = _extract_form_payload_list(
            r.text, clean_url
        )
        if not found_form:
            debug("Standard: No form found.")
            # If no form and no links, we might just return empty links but valid IMDB if found
            if imdb_id:
                return {"links": [], "imdb_id": imdb_id}
            return None

        # 3. POST
        encoded_payload = urlencode(payload_list)
        post_headers = headers.copy()
        post_headers.update(
            {"Referer": clean_url, "Content-Type": "application/x-www-form-urlencoded"}
        )

        debug(f"Standard: Posting to {action_url}")
        r_post = session.post(
            action_url,
            data=encoded_payload,
            headers=post_headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )

        if r_post.status_code == 403 or is_cloudflare_challenge(r_post.text):
            debug("Standard POST hit Cloudflare/403.")
            return None
        r_post.raise_for_status()

        # 4. Result
        links = _parse_links_strict(r_post.text)
        if links:
            debug(f"Standard: Success! Found {len(links)} links.")
            return {"links": links, "imdb_id": imdb_id}
        if _requires_manual_captcha(r_post.text):
            debug("Standard: Manual CAPTCHA required after POST.")
            return _protected_release_result(clean_url, imdb_id)

        debug("Standard: POST succeeded but returned no links. Trying FlareSolverr.")
        return {"links": [], "imdb_id": imdb_id, "inconclusive": True}

    except Exception as e:
        debug(f"Standard Strategy failed: {e}")
        return None


def _strategy_flaresolverr_loop(shared_state, url):
    """
    Robust Path: Uses FlareSolverr with a retry loop to handle
    Cloudflare token resets/reloads.
    Returns dict {'links': [], 'imdb_id': ...}
    """
    if not is_flaresolverr_available(shared_state):
        info("FlareSolverr not available. Skipping.")
        return {"links": [], "imdb_id": None}

    debug("Starting FlareSolverr Strategy (Robust Loop)...")
    session_id = str(uuid.uuid4())

    if not flaresolverr_create_session(shared_state, session_id):
        info("Could not create FlareSolverr session.")
        return {"links": [], "imdb_id": None}

    try:
        clean_url = _remove_fragment(url)

        # 1. Initial GET
        debug(f"FlareSolverr: GET {clean_url}")
        r_current = flaresolverr_get(
            shared_state,
            clean_url,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            session_id=session_id,
        )
        current_html = r_current.text

        # Extract IMDB from the first successful page load
        imdb_id = _extract_imdb_id(current_html)

        # 2. Submission Loop
        max_attempts = 3
        submitted_form = False

        for attempt in range(1, max_attempts + 1):
            # A. Check for success (links already visible?)
            links = _parse_links_strict(current_html)
            if links:
                debug(
                    f"FlareSolverr: Success! Found {len(links)} links on attempt {attempt}."
                )
                return {"links": links, "imdb_id": imdb_id}

            if _requires_manual_captcha(current_html):
                debug("FlareSolverr: Manual CAPTCHA required.")
                return _protected_release_result(clean_url, imdb_id)

            if attempt == max_attempts:
                break

                # B. Extract Form Data
            action_url, payload_list, found_form = _extract_form_payload_list(
                current_html, clean_url
            )

            if not found_form:
                if submitted_form:
                    warn(
                        "FlareSolverr: No links found after form submission; CAPTCHA assumed."
                    )
                    return _protected_release_result(clean_url, imdb_id)
                warn(f"FlareSolverr: Form not found on attempt {attempt}. Aborting.")
                return {"links": [], "imdb_id": imdb_id}

            # C. Encode & Submit
            encoded_payload = urlencode(payload_list)
            debug(f"FlareSolverr: Posting to {action_url} (Attempt {attempt})")

            r_post = flaresolverr_post(
                shared_state,
                action_url,
                data=encoded_payload,
                session_id=session_id,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            submitted_form = True

            # D. Update State
            current_html = r_post.text
            debug(f"FlareSolverr: POST Status: {r_post.status_code}")

            if "content-protector-access-form" in current_html:
                debug(
                    "FlareSolverr: Form detected in response (Challenge solved or invalid token). Retrying..."
                )
                continue

        if submitted_form:
            warn(
                "FlareSolverr: No links found after form submission attempts; CAPTCHA assumed."
            )
            return _protected_release_result(clean_url, imdb_id)

        warn("FlareSolverr: Max attempts reached without success.")
        return {"links": [], "imdb_id": imdb_id}

    except Exception as e:
        warn(f"FlareSolverr Error: {e}")
        return {"links": [], "imdb_id": None}

    finally:
        debug(f"Destroying FlareSolverr session: {session_id}")
        flaresolverr_destroy_session(shared_state, session_id)
