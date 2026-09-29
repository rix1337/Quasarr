# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import json
import re
import time
from typing import List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.linkcrypters.al import decrypt_content, solve_captcha
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.downloads.sources.helpers.anime_title import (
    ReleaseInfo,
)
from quasarr.downloads.sources.helpers.anime_title import (
    guess_release_title as _shared_guess_release_title,
)
from quasarr.downloads.sources.helpers.anime_title import (
    inject_subtitle_tokens_in_title as _shared_inject_subtitle_tokens_in_title,
)
from quasarr.downloads.sources.helpers.anime_title import (
    subtitle_lang_to_alpha2 as _shared_subtitle_lang_to_alpha2,
)
from quasarr.downloads.sources.helpers.anime_title import (
    subtitle_tokens as _shared_subtitle_tokens,
)
from quasarr.providers.cloudflare import (
    flaresolverr_create_session,
    flaresolverr_destroy_session,
)
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info, trace
from quasarr.providers.sessions.al import (
    fetch_via_flaresolverr,
    fetch_via_requests_session,
    invalidate_session,
    retrieve_and_validate_session,
    unwrap_flaresolverr_body,
)
from quasarr.providers.statistics import StatsHelper
from quasarr.providers.utils import is_flaresolverr_available


class Source(AbstractDownloadSource):
    initials = "al"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        AL source handler. Returns plain download links automatically by solving CAPTCHA.

        Note: The 'password' parameter is intentionally repurposed as release_id
        to ensure we download the correct release from the search results.
        This is set by the search module, not a user password.
        """
        # Check if FlareSolverr is available - AL requires it
        if not is_flaresolverr_available(shared_state):
            info(
                "This source requires FlareSolverr which is not configured. "
                "Please configure FlareSolverr in the web UI to use this site."
            )
            return {}

        release_id = _normalize_release_id(password)

        al = shared_state.values["config"]("Hostnames").get(Source.initials)

        sess = retrieve_and_validate_session(shared_state)
        if not sess:
            info(f"Could not retrieve valid session for {al}")
            mark_hostname_issue(Source.initials, "download", "Session error")
            return {}

        browser_session_id = flaresolverr_create_session(shared_state)
        links = []
        try:
            details_page = fetch_via_flaresolverr(
                shared_state,
                "GET",
                url,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                session_id=browser_session_id,
            )
            details_html = details_page.get("text", "")
            if not details_html:
                info(f"Failed to load details page for {title} at {url}")
                return {}

            episode_in_title = _extract_episode(title)

            title, release_id = _check_release(
                shared_state, details_html, release_id, title, episode_in_title
            )
            if release_id == 0:
                info(f"No valid release ID found for {title} - Download failed!")
                return {}

            if episode_in_title:
                selection = _resolve_episode_selection(
                    details_html, release_id, episode_in_title
                )
            else:
                selection = "cnl"

            anime_identifier = url.rstrip("/").split("/")[-1]

            info(f'Selected "Release {release_id}" from {url}')

            raw_request = json.dumps(
                ["media", anime_identifier, "downloads", release_id, selection]
            )
            b64 = base64.b64encode(raw_request.encode("ascii")).decode("ascii")

            post_url = f"https://www.{al}/ajax/captcha"
            ajax_headers = _build_ajax_headers()
            captcha_headers = _build_captcha_headers(al, url)
            payload = {"enc": b64, "response": "nocaptcha"}

            result = fetch_via_flaresolverr(
                shared_state,
                method="POST",
                target_url=post_url,
                post_data=payload,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                session_id=browser_session_id,
                request_headers=ajax_headers,
            )

            status = result.get("status_code")
            if not status == 200:
                info(f"FlareSolverr returned HTTP {status} for captcha request")
                StatsHelper(shared_state).increment_failed_decryptions_automatic()
                return {}
            else:
                text = result.get("text", "")
                try:
                    response_json = result["json"]
                except ValueError:
                    info(f"Unexpected response when initiating captcha: {text}")
                    StatsHelper(shared_state).increment_failed_decryptions_automatic()
                    return {}

                code = response_json.get("code", "")
                message = response_json.get("message", "")
                content_items = response_json.get("content", [])

                tries = 0
                if code == "success" and content_items:
                    info("CAPTCHA not required")
                elif message == "cnl_login":
                    info("Login expired, re-creating session...")
                    invalidate_session(shared_state)
                else:
                    tries = 0
                    while tries < 3:
                        try:
                            tries += 1
                            info(
                                f"Starting attempt {tries} to solve CAPTCHA for "
                                f"{f'episode {episode_in_title}' if selection and selection != 'cnl' else 'all links'}"
                            )
                            attempt = solve_captcha(
                                Source.initials,
                                shared_state,
                                fetch_via_flaresolverr,
                                fetch_via_requests_session,
                                session_id=browser_session_id,
                                request_headers=captcha_headers,
                            )

                            solved = (
                                unwrap_flaresolverr_body(attempt.get("response")) == "1"
                            )
                            captcha_id = attempt.get("captcha_id", None)

                            if solved and captcha_id:
                                payload = {
                                    "enc": b64,
                                    "response": "captcha",
                                    "captcha-idhf": 0,
                                    "captcha-hf": captcha_id,
                                }
                                # Validate through the same requests.Session that
                                # solved the CAPTCHA (rT:1/images/rT:2). AL binds the
                                # solved CAPTCHA to the solving client; validating via
                                # the FlareSolverr browser hits a different cookie jar
                                # and AL rejects it with "The captcha ID was invalid".
                                check_solution = fetch_via_requests_session(
                                    shared_state,
                                    method="POST",
                                    target_url=post_url,
                                    post_data=payload,
                                    timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                                    request_headers=ajax_headers,
                                )
                                try:
                                    response_json = check_solution.json()
                                except ValueError as e:
                                    raise RuntimeError(
                                        f"Unexpected /ajax/captcha response: {check_solution.text}"
                                    ) from e

                                code = response_json.get("code", "")
                                message = response_json.get("message", "")
                                content_items = response_json.get("content", [])

                                if code == "success":
                                    if content_items:
                                        info(
                                            "CAPTCHA solved successfully on attempt {}.".format(
                                                tries
                                            )
                                        )
                                        break
                                    else:
                                        info(
                                            "CAPTCHA was solved, but no links are available for the selection!"
                                        )
                                        StatsHelper(
                                            shared_state
                                        ).increment_failed_decryptions_automatic()
                                        return {}
                                elif message == "cnl_login":
                                    info("Login expired, re-creating session...")
                                    invalidate_session(shared_state)
                                else:
                                    info(
                                        f"CAPTCHA POST returned code={code}, message={message}. Retrying... (attempt {tries})"
                                    )

                                    if "slowndown" in str(message).lower():
                                        wait_period = 30
                                        info(
                                            f"CAPTCHAs solved too quickly. Waiting {wait_period} seconds before next attempt..."
                                        )
                                        time.sleep(wait_period)
                            else:
                                info(
                                    f"CAPTCHA solver returned invalid solution, retrying... (attempt {tries})"
                                )

                        except RuntimeError as e:
                            info(f"Error solving CAPTCHA: {e}")
                            mark_hostname_issue(
                                Source.initials,
                                "download",
                                str(e) if "e" in dir() else "Download error",
                            )
                        else:
                            info(
                                f"CAPTCHA solver returned invalid solution, retrying... (attempt {tries})"
                            )

                if code != "success":
                    info(
                        f"CAPTCHA solution failed after {tries} attempts. Your IP is likely banned - "
                        f"Code: {code}, Message: {message}"
                    )
                    invalidate_session(shared_state)
                    StatsHelper(shared_state).increment_failed_decryptions_automatic()
                    return {}

                try:
                    links = decrypt_content(content_items, mirrors)
                    debug(f"Decrypted URLs: {links}")
                except Exception as e:
                    info(f"Error during decryption: {e}")
                    mark_hostname_issue(
                        Source.initials,
                        "download",
                        str(e) if "e" in dir() else "Download error",
                    )
        except Exception as e:
            info(f"Error loading download: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )
            invalidate_session(shared_state)
        finally:
            if browser_session_id:
                flaresolverr_destroy_session(shared_state, browser_session_id)

        success = bool(links)
        if success:
            StatsHelper(shared_state).increment_captcha_decryptions_automatic()
        else:
            StatsHelper(shared_state).increment_failed_decryptions_automatic()

        links_with_mirrors = [[url, _derive_mirror(url)] for url in links]

        return {"links": links_with_mirrors, "password": f"www.{al}", "title": title}


def _build_ajax_headers():
    return {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
    }


def _build_captcha_headers(al, referer):
    headers = _build_ajax_headers()
    headers.update(
        {
            "Origin": f"https://www.{al}",
            "Referer": referer,
        }
    )
    return headers


def _roman_to_int(r: str) -> int:
    roman_map = {"I": 1, "V": 5, "X": 10}
    total = 0
    prev = 0
    for ch in r.upper()[::-1]:
        val = roman_map.get(ch, 0)
        if val < prev:
            total -= val
        else:
            total += val
        prev = val
    return total


def _normalize_release_id(raw_release_id) -> int:
    """
    AL uses download-link password to transport release IDs.
    Older/invalid payloads can provide None/empty/non-numeric values.
    """
    if raw_release_id in (None, "", "None"):
        return 0
    try:
        return int(str(raw_release_id).strip())
    except (TypeError, ValueError):
        return 0


def _derive_mirror(url):
    try:
        hostname = urlparse(url).netloc.lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        parts = hostname.split(".")
        return parts[-2] if len(parts) >= 2 else hostname
    except:
        return "unknown"


def _extract_season_from_synonyms(soup):
    """
    Returns the first season found as "Season N" in the Synonym(s) <td>, or None.
    Only scans the synonyms cell, no fallback to whole document.
    """
    syn_td = None
    for tr in soup.select("tr"):
        th = tr.find("th")
        if th and "synonym" in th.get_text(strip=True).lower():
            syn_td = tr.find("td")
            break

    if not syn_td:
        return None

    text = syn_td.get_text(" ", strip=True)

    synonym_season_patterns = [
        re.compile(r"\b(?:Season|Staffel)\s*0?(\d+)\b", re.IGNORECASE),
        re.compile(r"\b0?(\d+)(?:st|nd|rd|th)\s+Season\b", re.IGNORECASE),
        re.compile(r"\b(\d+)\.\s*Staffel\b", re.IGNORECASE),
        re.compile(r"\bS0?(\d+)\b", re.IGNORECASE),  # S02, s2, etc.
        re.compile(r"\b([IVXLCDM]+)\b(?=\s*$)"),  # uppercase Roman at end
    ]

    for pat in synonym_season_patterns:
        m = pat.search(text)
        if not m:
            continue

        tok = m.group(0)
        # Digit match → extract number
        dm = re.search(r"(\d+)", tok)
        if dm:
            return int(dm.group(1))
        # Uppercase Roman → convert & return
        if tok.isupper() and re.fullmatch(r"[IVXLCDM]+", tok):
            return _roman_to_int(tok)

    return None


def _find_season_in_release_notes(soup):
    """
    Iterates through all <tr> rows with a "Release Notes" <th> (case-insensitive).
    Returns the first season number found as an int, or None if not found.
    """
    patterns = [
        re.compile(r"\b(?:Season|Staffel)\s*0?(\d+)\b", re.IGNORECASE),
        re.compile(r"\b0?(\d+)(?:st|nd|rd|th)\s+Season\b", re.IGNORECASE),
        re.compile(r"\b(\d+)\.\s*Staffel\b", re.IGNORECASE),
        re.compile(r"\bS(?:eason)?0?(\d+)\b", re.IGNORECASE),
        re.compile(r"\b([IVXLCDM]+)\b(?=\s*$)"),  # uppercase Roman at end
    ]

    for tr in soup.select("tr"):
        th = tr.find("th")
        if not th:
            continue

        header = th.get_text(strip=True)
        if "release " not in header.lower():  # release notes or release anmerkungen
            continue

        td = tr.find("td")
        if not td:
            continue

        content = td.get_text(" ", strip=True)
        for pat in patterns:
            m = pat.search(content)
            if not m:
                continue

            token = m.group(1)
            # Roman numeral detection only uppercase
            if pat.pattern.endswith("(?=\\s*$)"):
                if token.isupper():
                    return _roman_to_int(token)
                else:
                    continue
            return int(token)

    return None


def _extract_season_number_from_title(page_title, release_type, release_title=""):
    """
    Extracts the season number from the given page title.

    Priority is given to standard patterns like S01/E01 or R2 in the optional release title.
    If no match is found, it attempts to extract based on keywords like "Season"/"Staffel"
    or trailing numbers/roman numerals in the page title.

    Args:
        page_title (str): The title of the page, used as a fallback.
        release_type (str): The type of release (e.g., 'series').
        release_title (Optional, str): The title of the release.

    Returns:
        int: The extracted or inferred season number. Defaults to 1 if not found.
    """
    season_num = None

    if release_title:
        match = re.search(
            r"\.(?:S(\d{1,4})|R(2))(?:E\d{1,4})?", release_title, re.IGNORECASE
        )
        if match:
            if match.group(1) is not None:
                season_num = int(match.group(1))
            elif match.group(2) is not None:
                season_num = int(match.group(2))

    if season_num is None:
        page_title = page_title or ""
        if (
            "staffel" in page_title.lower()
            or "season" in page_title.lower()
            or release_type == "series"
        ):
            match = re.search(
                r"\b(?:Season|Staffel)\s+(\d+|[IVX]+)\b|\bR(2)\b",
                page_title,
                re.IGNORECASE,
            )
            if match:
                if match.group(1) is not None:
                    num = match.group(1)
                    season_num = int(num) if num.isdigit() else _roman_to_int(num)
                elif match.group(2) is not None:
                    season_num = int(match.group(2))
            else:
                trailing_match = re.search(
                    r"\s+([2-9]\d*|[IVXLCDM]+)\s*$", page_title, re.IGNORECASE
                )
                if trailing_match:
                    num = trailing_match.group(1)
                    season_candidate = int(num) if num.isdigit() else _roman_to_int(num)
                    if season_candidate >= 2:
                        season_num = season_candidate

            if season_num is None:
                season_num = 1

    return season_num


def _subtitle_lang_to_alpha2(lang: str) -> Optional[str]:
    return _shared_subtitle_lang_to_alpha2(lang)


def _subtitle_tokens(subtitle_langs: List[str]) -> List[str]:
    return _shared_subtitle_tokens(subtitle_langs)


def _inject_subtitle_tokens_in_title(title: str, subtitle_langs: List[str]) -> str:
    return _shared_inject_subtitle_tokens_in_title(title, subtitle_langs)


def _parse_info_from_feed_entry(block, series_page_title, release_type) -> ReleaseInfo:
    """
    Parse a BeautifulSoup block from the feed entry into ReleaseInfo.
    """
    text = block.get_text(separator=" ", strip=True)

    # detect season
    season_num = _extract_season_number_from_title(series_page_title, release_type)

    # detect episodes
    episode_min: Optional[int] = None
    episode_max: Optional[int] = None
    m_ep = re.search(r"Episode\s+(\d+)(?:-(\d+))?", text)
    if m_ep:
        episode_min = int(m_ep.group(1))
        episode_max = int(m_ep.group(2)) if m_ep.group(2) else episode_min

    # parse audio flags
    audio_langs: List[str] = []
    audio_icon = block.find("i", class_="fa-volume-up")
    if audio_icon:
        for sib in audio_icon.find_next_siblings():
            if sib.name == "i" and "fa-closed-captioning" in sib.get("class", []):
                break
            if sib.name == "i" and "flag" in sib.get("class", []):
                code = sib["class"][1].replace("flag-", "").lower()
                audio_langs.append(
                    {"jp": "Japanese", "de": "German", "en": "English"}.get(
                        code, code.title()
                    )
                )

    # parse subtitle flags
    subtitle_langs: List[str] = []
    subtitle_icon = block.find("i", class_="fa-closed-captioning")
    if subtitle_icon:
        for sib in subtitle_icon.find_next_siblings():
            if sib.name == "i" and "flag" in sib.get("class", []):
                code = sib["class"][1].replace("flag-", "").lower()
                subtitle_langs.append(
                    {"jp": "Japanese", "de": "German", "en": "English"}.get(
                        code, code.title()
                    )
                )

    # resolution
    m_res = re.search(r":\s*([0-9]{3,4}p)", text, re.IGNORECASE)
    resolution = m_res.group(1) if m_res else "1080p"

    # source not available in feed
    source = "WEB-DL"
    # video codec not available in feed
    video = "x264"

    # release group
    span = block.find("span")
    if span:
        grp = span.get_text().split(":", 1)[-1].strip()
        release_group = grp.replace(" ", "").replace("-", "")
    else:
        release_group = ""

    return ReleaseInfo(
        release_title=None,
        audio_langs=audio_langs,
        subtitle_langs=subtitle_langs,
        episode_title=None,
        resolution=resolution,
        audio="",
        video=video,
        source=source,
        release_group=release_group,
        season_part=None,
        season=season_num,
        episode_min=episode_min,
        episode_max=episode_max,
    )


def _parse_info_from_download_item(
    tab,
    content,
    page_title=None,
    release_type=None,
    requested_season=False,
    requested_episode=None,
) -> ReleaseInfo:
    """
    Parse a BeautifulSoup 'tab' from a download item into ReleaseInfo.
    """
    # notes
    notes_td = tab.select_one("tr:has(th>i.fa-info) td")
    notes_text = notes_td.get_text(strip=True) if notes_td else ""
    notes_lower = notes_text.lower()
    trace(
        f"parse_download_item tab={tab.get('id', '')} "
        f"page_title='{page_title}' requested_season={requested_season} "
        f"requested_episode={requested_episode} notes_text='{notes_text}'"
    )

    release_title = None
    if notes_text:
        rn_with_dots = notes_text.replace(" ", ".").replace(".-.", "-")
        rn_no_dot_duplicates = re.sub(r"\.{2,}", ".", rn_with_dots)
        trace(
            f"notes_transformed tab={tab.get('id', '')} "
            f"dotted='{rn_with_dots}' deduped='{rn_no_dot_duplicates}'"
        )
        if "." in rn_with_dots and "-" in rn_with_dots:
            # Check if string ends with Group tag (word after dash) - this should prevent false positives
            if re.search(r"-[\s.]?\w+$", rn_with_dots):
                release_title = rn_no_dot_duplicates
                trace(
                    f"release_title accepted from notes "
                    f"tab={tab.get('id', '')}: '{release_title}'"
                )

    # resolution
    res_td = tab.select_one("tr:has(th>i.fa-desktop) td")
    resolution = "1080p"
    if res_td:
        match = re.search(r"(\d+)\s*x\s*(\d+)", res_td.get_text(strip=True))
        if match:
            h = int(match.group(2))
            resolution = "2160p" if h >= 2000 else "1080p" if h >= 1000 else "720p"

    # audio and subtitles
    audio_codes = [
        icon["class"][1].replace("flag-", "")
        for icon in tab.select("tr:has(th>i.fa-volume-up) i.flag")
    ]
    audio_langs = [
        {"jp": "Japanese", "de": "German", "en": "English"}.get(c, c.title())
        for c in audio_codes
    ]
    sub_codes = [
        icon["class"][1].replace("flag-", "")
        for icon in tab.select("tr:has(th>i.fa-closed-captioning) i.flag")
    ]
    subtitle_langs = [
        {"jp": "Japanese", "de": "German", "en": "English"}.get(c, c.title())
        for c in sub_codes
    ]

    # audio codec
    if "flac" in notes_lower:
        audio = "FLAC"
    elif "aac" in notes_lower:
        audio = "AAC"
    elif "opus" in notes_lower:
        audio = "Opus"
    elif "mp3" in notes_lower:
        audio = "MP3"
    elif "pcm" in notes_lower:
        audio = "PCM"
    elif "dts" in notes_lower:
        audio = "DTS"
    elif "ac3" in notes_lower or "eac3" in notes_lower:
        audio = "AC3"
    else:
        audio = ""

    # source
    if re.search(r"(web-dl|webdl|webrip)", notes_lower):
        source = "WEB-DL"
    elif re.search(r"(blu-ray|\bbd\b|bluray)", notes_lower):
        source = "BluRay"
    elif re.search(r"(hdtv|tvrip)", notes_lower):
        source = "HDTV"
    else:
        source = "WEB-DL"

    if "265" in notes_lower or "hevc" in notes_lower:
        video = "x265"
    elif "av1" in notes_lower:
        video = "AV1"
    elif "avc" in notes_lower:
        video = "AVC"
    elif "xvid" in notes_lower:
        video = "Xvid"
    elif "mpeg" in notes_lower:
        video = "MPEG"
    elif "vc-1" in notes_lower:
        video = "VC-1"
    else:
        video = "x264"

    # release group
    grp_td = tab.select_one("tr:has(th>i.fa-child) td")
    if grp_td:
        grp = grp_td.get_text(strip=True)
        release_group = grp.replace(" ", "").replace("-", "")
    else:
        release_group = ""

    # determine season
    if requested_season:
        season_num = _extract_season_from_synonyms(content)
        if not season_num:
            season_num = _find_season_in_release_notes(content)
        if not season_num:
            season_num = _extract_season_number_from_title(
                page_title, release_type, release_title=release_title
            )
    else:
        season_num = None

    # check if season part info is present
    season_part: Optional[int] = None
    if page_title:
        match = re.search(
            r"(?i)\b(?:Part|Teil)\s+(\d+|[IVX]+)\b", page_title, re.IGNORECASE
        )
        if match:
            num = match.group(1)
            season_part = int(num) if num.isdigit() else _roman_to_int(num)
            part_string = f"Part.{season_part}"
            if release_title and part_string not in release_title:
                release_title = re.sub(
                    r"\.(German|Japanese|English)\.",
                    f".{part_string}.\\1.",
                    release_title,
                    count=1,
                )

    # determine if optional episode exists on release page
    episode_min: Optional[int] = None
    episode_max: Optional[int] = None
    if requested_episode:
        episodes_div = tab.find("div", class_="episodes")
        if episodes_div:
            episode_links = episodes_div.find_all(
                "a", attrs={"data-loop": re.compile(r"^\d+$")}
            )
            total_episodes = len(episode_links)
            if total_episodes > 0:
                ep = int(requested_episode)
                if ep <= total_episodes:
                    episode_min = 1
                    episode_max = total_episodes
                    if release_title:
                        release_title = re.sub(
                            r"(?<=\.)S(\d{1,4})(?=\.)",
                            lambda m: f"S{int(m.group(1)):02d}E{ep:02d}",
                            release_title,
                            count=1,
                            flags=re.IGNORECASE,
                        )

    if release_title:
        release_title = _inject_subtitle_tokens_in_title(release_title, subtitle_langs)

    trace(
        f"parse_download_item result tab={tab.get('id', '')} "
        f"release_title='{release_title}' season={season_num} "
        f"episode_min={episode_min} episode_max={episode_max}"
    )

    return ReleaseInfo(
        release_title=release_title,
        audio_langs=audio_langs,
        subtitle_langs=subtitle_langs,
        episode_title=None,
        resolution=resolution,
        audio=audio,
        video=video,
        source=source,
        release_group=release_group,
        season_part=season_part,
        season=season_num,
        episode_min=episode_min,
        episode_max=episode_max,
    )


def _guess_title(page_title, release_info: ReleaseInfo) -> str:
    return _shared_guess_release_title(page_title, release_info)


def _check_release(shared_state, details_html, release_id, title, episode_in_title):
    soup = BeautifulSoup(details_html, "html.parser")
    release_id = _normalize_release_id(release_id)

    if release_id == 0:
        info(
            "Feed download detected, hard-coding release_id to 1 to achieve successful download"
        )
        release_id = 1
        # The following logic works, but the highest release ID sometimes does not have the desired episode
        #
        # If download was started from the feed, the highest download id is typically the best option
        # panes = soup.find_all("div", class_="tab-pane")
        # max_id = None
        # for pane in panes:
        #     pane_id = pane.get("id", "")
        #     match = re.match(r"download_(\d+)$", pane_id)
        #     if match:
        #         num = int(match.group(1))
        #         if max_id is None or num > max_id:
        #             max_id = num
        # if max_id:
        #     release_id = max_id

    tab = soup.find("div", class_="tab-pane", id=f"download_{release_id}")
    if tab:
        try:
            # We re-guess the title from the details page
            # This ensures, that downloads initiated by the feed (which has limited/incomplete data) yield
            # the best possible title for the download (including resolution, audio, video, etc.)
            page_title_info = soup.find("title").text.strip().rpartition(" (")
            page_title = page_title_info[0].strip()
            release_type_info = page_title_info[2].strip()
            if "serie" in release_type_info.lower():
                release_type = "series"
            else:
                release_type = "movie"

            release_info = _parse_info_from_download_item(
                tab,
                soup,
                page_title=page_title,
                release_type=release_type,
                requested_season=True if release_type == "series" else False,
                requested_episode=episode_in_title,
            )
            real_title = release_info.release_title
            if real_title:
                if real_title.lower() != title.lower():
                    info(
                        f'Identified true release title "{real_title}" on details page'
                    )
                    return real_title, release_id
            else:
                # Overwrite values so guessing the title only applies the requested episode
                if episode_in_title:
                    release_info.episode_min = int(episode_in_title)
                    release_info.episode_max = int(episode_in_title)

                guessed_title = _guess_title(page_title, release_info)
                if guessed_title and guessed_title.lower() != title.lower():
                    info(
                        f'Adjusted guessed release title to "{guessed_title}" from details page'
                    )
                    return guessed_title, release_id
        except Exception as e:
            info(f"Error guessing release title from release: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )

    return title, release_id


def _resolve_episode_selection(details_html, release_id, episode: int) -> int:
    """
    Map a requested episode number to the zero-based row index (data-loop) of a release.

    Rows are labeled like "Episode 003" or "Episode 001-002" (merged double episodes),
    so the row position does not always equal episode - 1. Falls back to that position
    when no row label covers the requested episode.
    """
    fallback = episode - 1
    soup = BeautifulSoup(details_html, "html.parser")
    tab = soup.find("div", class_="tab-pane", id=f"download_{release_id}")
    episodes_div = tab.find("div", class_="episodes") if tab else None
    if not episodes_div:
        return fallback

    for row in episodes_div.find_all("a", attrs={"data-loop": re.compile(r"^\d+$")}):
        # Label directly follows the row number, e.g. "003 Episode 001-002: Title".
        # Anchored so episode titles like "Chikara - Episode 1" are not mistaken for it.
        match = re.match(
            r"\d+\s+Episode\s+(\d+)(?:\s*-\s*(\d+))?(?=\s*:|\s*$)",
            row.get_text(" ", strip=True),
        )
        if not match:
            continue
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) else first
        if first <= episode <= last:
            selection = int(row["data-loop"])
            if selection != fallback:
                info(
                    f"Episode {episode} is row {selection + 1} of release {release_id} "
                    f'("{match.group(0)}"), not row {episode}'
                )
            return selection

    return fallback


def _extract_episode(title: str) -> int | None:
    match = re.search(r"\bS\d{1,4}E(\d+)\b(?![\-E\d])", title)
    if match:
        return int(match.group(1))

    if not re.search(r"\bS\d{1,4}\b", title):
        match = re.search(r"\.E(\d+)\b(?![\-E\d])", title)
        if match:
            return int(match.group(1))

    return None
