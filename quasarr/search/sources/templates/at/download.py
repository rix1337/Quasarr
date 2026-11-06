# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    SHARE_HOSTERS_LOWERCASE,
)
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.downloads.sources.helpers.anime_title import (
    ReleaseInfo,
    guess_release_title,
)
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import info
from quasarr.providers.utils import sanitize_string
from quasarr.providers.xem_metadata import get_all_season_names

_SEASON_EP_REGEX = re.compile(
    r"\bS(?:eason)?\s*0*(\d{1,3})\s*[.\-_ ]?(?:E|EP|Episode)\s*0*(\d{1,4})(?:\s*[-+]\s*0*(\d{1,4}))?\b",
    re.I,
)
_SEASON_DASH_EP_REGEX = re.compile(
    r"\bS(?:eason)?\s*0*(\d{1,3})\s*-\s*0*(\d{1,4})(?:\s*[-+]\s*0*(\d{1,4}))?\b",
    re.I,
)
_SEASON_ONLY_REGEX = re.compile(
    r"\b(?:Season|Staffel)\s*0*(\d{1,3})\b|\b0*(\d{1,3})(?:st|nd|rd|th)\s+Season\b|\bS0*(\d{1,3})\b",
    re.I,
)
_ABSOLUTE_EP_REGEX = re.compile(
    r"\b(?:EP?|Episode)\s*0*(\d{1,4})(?:\s*[-+]\s*0*(\d{1,4}))?\b", re.I
)
_ABSOLUTE_RANGE_REGEX = re.compile(r"[\[(]0*(\d{1,4})\s*[-+]\s*0*(\d{1,4})[\])]", re.I)
_TITLE_DASH_EP_REGEX = re.compile(
    r"\s-\s0*(\d{1,4})(?:\s*[-+]\s*0*(\d{1,4}))?(?=\s[\[(]|\s(?:WEB|BD|BluRay|CR|DVD|HDTV|NF|AMZN|BILI|IQIYI)|$)",
    re.I,
)
_STANDALONE_EP_REGEX = re.compile(
    r"(?:\s-\s|\s)0*(\d{1,4})(?:v\d+)?(?:\s*[-+]\s*0*(\d{1,4}))?(?=\s*(?:END\b|FINAL\b|V\d+\b|[\[(]|\||$))",
    re.I,
)
_PART_REGEX = re.compile(r"\b(?:Part|Teil)\s+(\d+)\b", re.I)
_EPISODE_TITLE_STOP_REGEX = re.compile(
    r"""
    (?=
        \s*(?:\(|\[)?
        (?:
            \d{3,4}p|4k|
            cr|nf|amzn|bili|iqiyi|
            web(?:-dl|dl|rip)?|blu-?ray|bluray|bd|hdtv|tvrip|
            aac(?:\d(?:\.\d)?)?|ddp\d(?:\.\d)?|dd\d(?:\.\d)?|
            eac3|ac3|flac|opus|mp3|pcm|dts|
            hevc|avc|av1|x26[45]|h[\s.]?26[45]|
            10bit|multi(?:[- ]?sub(?:s)?)|dual(?:[- ]audio)?|
            english\s+dub|german\s+dub|weekly|batch
        )\b
    )
    """,
    re.I | re.X,
)
_SOURCE_TAG_PATTERNS = (
    (re.compile(r"\bcr\b", re.I), "CR"),
    (re.compile(r"\bnf\b", re.I), "NF"),
    (re.compile(r"\bamzn\b", re.I), "AMZN"),
    (re.compile(r"\bbili\b", re.I), "BILI"),
    (re.compile(r"\biqiyi\b", re.I), "IQIYI"),
)
_AUDIO_CODEC_PATTERNS = (
    (re.compile(r"\bDDP\d(?:\.\d)?\b", re.I), lambda m: m.group(0).upper()),
    (re.compile(r"\bDD\d(?:\.\d)?\b", re.I), lambda m: m.group(0).upper()),
    (re.compile(r"\bAAC\d(?:\.\d)?\b", re.I), lambda m: m.group(0).upper()),
    (re.compile(r"\bEAC3\b", re.I), lambda m: "EAC3"),
    (re.compile(r"\bAC3\b", re.I), lambda m: "AC3"),
    (re.compile(r"\bFLAC\b", re.I), lambda m: "FLAC"),
    (re.compile(r"\bOPUS\b", re.I), lambda m: "Opus"),
    (re.compile(r"\bMP3\b", re.I), lambda m: "MP3"),
    (re.compile(r"\bPCM\b", re.I), lambda m: "PCM"),
    (re.compile(r"\bDTS\b", re.I), lambda m: "DTS"),
    (re.compile(r"\bAAC\b", re.I), lambda m: "AAC"),
)
_DIRECT_DOWNLOAD_MIRROR_ALIASES = {
    "down": "mdiaload",
}
_JAPANESE_SEASON_NAMES = {
    "ni": 2,
    "san": 3,
    "yon": 4,
    "go": 5,
    "roku": 6,
    "nana": 7,
    "shichi": 7,
    "hachi": 8,
    "kyuu": 9,
    "ku": 9,
    "juu": 10,
}


class Source(AbstractDownloadSource):
    initials = "at"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        headers = {"User-Agent": shared_state.values["user_agent"]}

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as e:
            info(f"Could not load release page for {title}: {e}")
            mark_hostname_issue(Source.initials, "download", str(e) or "Download error")
            return {"links": [], "imdb_id": None}

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            raw_title = _extract_release_title(soup)
            series_title = _extract_series_title_from_release_page(soup)
            subtitle_langs = _extract_subtitle_langs_from_release_page(soup)
            release_info = _build_release_info_from_title(raw_title, subtitle_langs)
            page_title, release_info = _resolve_title_context(
                series_title
                or _extract_series_title_from_raw_title(raw_title)
                or raw_title,
                raw_title,
                release_info,
            )
            resolved_title = guess_release_title(page_title, release_info)

            links = []
            for cell in _iter_link_cells(soup):
                links.extend(
                    _extract_direct_links_from_anchors(cell.find_all("a"), mirrors)
                )

            links = _dedupe_links(links)
            if links:
                clear_hostname_issue(Source.initials)

            return {"links": links, "imdb_id": None, "title": resolved_title}
        except Exception as e:
            info(f"Could not parse release page for {title}: {e}")
            mark_hostname_issue(Source.initials, "download", str(e) or "Download error")
            return {"links": [], "imdb_id": None}


def _iter_link_cells(soup):
    for row in soup.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue

        label = th.get_text(" ", strip=True).lower()
        if label in {"source links", "extractions"}:
            yield td


def _extract_direct_links_from_anchors(anchors, mirrors=None):
    requested_mirrors = {
        _normalize_requested_mirror(mirror) for mirror in (mirrors or []) if mirror
    }
    links = []

    for anchor in anchors:
        href = (anchor.get("href") or "").strip()
        mirror = _derive_supported_mirror_from_url(href)
        if not mirror:
            continue

        if requested_mirrors and mirror not in requested_mirrors:
            continue

        links.append([href, mirror])

    return _dedupe_links(links)


def _dedupe_links(links):
    deduped = []
    seen = set()

    for href, mirror in links:
        if href in seen:
            continue
        seen.add(href)
        deduped.append([href, mirror])

    return deduped


def _normalize_requested_mirror(mirror_name):
    normalized = str(mirror_name or "").lower().strip()

    if "://" in normalized:
        parsed = urlparse(normalized)
        normalized = parsed.netloc or parsed.path

    if normalized.startswith("www."):
        normalized = normalized[4:]

    normalized = normalized.split("/", 1)[0]
    normalized = normalized.split(":", 1)[0]
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]

    return _DIRECT_DOWNLOAD_MIRROR_ALIASES.get(normalized, normalized)


def _derive_supported_mirror_from_url(url):
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except Exception:
        return None

    if not hostname:
        return None

    if hostname.startswith("www."):
        hostname = hostname[4:]

    provider = hostname.split(".", 1)[0]
    provider = _DIRECT_DOWNLOAD_MIRROR_ALIASES.get(provider, provider)
    if provider in SHARE_HOSTERS_LOWERCASE:
        return provider
    return None


def _extract_release_title(soup):
    title_node = soup.select_one("#title")
    return title_node.get_text(" ", strip=True) if title_node else ""


def _extract_series_title_from_release_page(soup):
    for row in soup.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue

        if not th.get_text(" ", strip=True).lower().startswith("series"):
            continue

        anchor = td.find("a")
        if anchor:
            return _clean_series_title(
                anchor.get("title") or anchor.get_text(" ", strip=True)
            )

    breadcrumb_links = soup.select("#nav_bc a")
    if len(breadcrumb_links) >= 2:
        return _clean_series_title(
            breadcrumb_links[-2].get("title")
            or breadcrumb_links[-2].get_text(" ", strip=True)
        )

    return ""


def _extract_series_title_from_listing_entry(entry):
    anchor = entry.select_one("span.serieslink a")
    if not anchor:
        return ""

    return _clean_series_title(anchor.get("title") or anchor.get_text(" ", strip=True))


def _extract_subtitle_langs_from_release_page(soup):
    for row in soup.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue

        if th.get_text(" ", strip=True).lower() != "extractions":
            continue

        return _extract_subtitle_langs_from_links(td)

    return []


def _extract_subtitle_langs_from_links(container):
    subtitle_langs = []

    for anchor in container.find_all("a", href=True):
        href = (anchor.get("href") or "").strip().lower()
        if "_track" not in href:
            continue

        text = anchor.get_text(" ", strip=True)
        for match in re.findall(r"\[([^\]]+)\]", text):
            for token in re.split(r"[\s,/_-]+", match):
                _add_subtitle_lang(token, subtitle_langs)

        for token in re.split(r"[\s,/_-]+", re.sub(r"\[[^\]]+\]", " ", text)):
            _add_subtitle_lang(token, subtitle_langs)

    return subtitle_langs


def _add_subtitle_lang(token, subtitle_langs):
    token = token.strip().lower()
    if token in {"", "ass", "ssa", "srt", "sub", "subs", "forced", "signs", "cr"}:
        return

    if token not in subtitle_langs:
        subtitle_langs.append(token)


def _clean_series_title(series_title):
    cleaned = str(series_title or "").replace("...", "").strip()
    cleaned = re.sub(r"\s*\(\d{4}\)\s*$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _strip_file_extension(title):
    return re.sub(
        r"\.(?:mkv|mp4|avi|m2ts|mov|zip|7z)$", "", str(title or ""), flags=re.I
    )


def _build_release_info_from_title(raw_title, subtitle_langs=None, forced_season=None):
    raw_title = _strip_file_extension(raw_title)
    subtitle_langs = list(subtitle_langs or [])
    title_lower = raw_title.lower()

    season = _extract_season_number(raw_title)
    if season is None and forced_season is not None:
        season = int(forced_season)

    episode_min, episode_max = _extract_episode_range(raw_title, season)

    return ReleaseInfo(
        release_title=None,
        audio_langs=_extract_audio_langs(title_lower),
        subtitle_langs=subtitle_langs,
        episode_title=_extract_episode_title(raw_title),
        resolution=_extract_resolution(title_lower),
        audio=_extract_audio_codec(raw_title),
        video=_extract_video_codec(raw_title),
        source=_extract_source(title_lower),
        release_group=_extract_release_group(raw_title),
        season_part=_extract_season_part(raw_title),
        season=season,
        episode_min=episode_min,
        episode_max=episode_max,
    )


def _extract_season_number(raw_title):
    season_ep_match = _SEASON_EP_REGEX.search(raw_title)
    if season_ep_match:
        return int(season_ep_match.group(1))

    season_dash_match = _SEASON_DASH_EP_REGEX.search(raw_title)
    if season_dash_match:
        return int(season_dash_match.group(1))

    season_match = _SEASON_ONLY_REGEX.search(raw_title)
    if season_match:
        for value in season_match.groups():
            if value:
                return int(value)

    return None


def _extract_season_hint_from_title(title):
    normalized_title = str(title or "")
    if not normalized_title:
        return None

    explicit_match = _SEASON_ONLY_REGEX.search(normalized_title)
    if explicit_match:
        for value in explicit_match.groups():
            if value:
                return int(value)

    ordinal_match = re.search(
        r"\b0*(\d{1,2})(?:st|nd|rd|th)\s+Season\b", normalized_title, re.I
    )
    if ordinal_match:
        return int(ordinal_match.group(1))

    japanese_match = re.search(r"\b([A-Za-z]+)\s+no\s+Shou\b", normalized_title, re.I)
    if japanese_match:
        mapped = _JAPANESE_SEASON_NAMES.get(japanese_match.group(1).lower())
        if mapped:
            return mapped

    return None


def _resolve_trailing_season_context(page_title):
    trailing_match = re.search(
        r"^(?P<base>.*\S)\s+(?P<season>[2-9]|1\d)\s*$",
        str(page_title or "").strip(),
    )
    if not trailing_match:
        return None, None

    base_title = _clean_series_title(trailing_match.group("base"))
    if not base_title:
        return None, None

    season = int(trailing_match.group("season"))
    season_names = _get_cached_season_names(base_title)
    if not season_names:
        return None, None

    known_seasons = {
        int(season_key) for season_key in season_names if str(season_key).isdigit()
    }
    if season not in known_seasons:
        return None, None

    canonical_title = season_names.get("all") or base_title
    if isinstance(canonical_title, list):
        canonical_title = canonical_title[0] if canonical_title else base_title

    return str(canonical_title or base_title), season


def _extract_episode_range(raw_title, season):
    season_ep_match = _SEASON_EP_REGEX.search(raw_title)
    if season_ep_match:
        episode_min = int(season_ep_match.group(2))
        episode_max = int(season_ep_match.group(3) or episode_min)
        return episode_min, episode_max

    season_dash_match = _SEASON_DASH_EP_REGEX.search(raw_title)
    if season_dash_match:
        episode_min = int(season_dash_match.group(2))
        episode_max = int(season_dash_match.group(3) or episode_min)
        return episode_min, episode_max

    absolute_match = _ABSOLUTE_EP_REGEX.search(raw_title)
    if absolute_match:
        episode_min = int(absolute_match.group(1))
        episode_max = int(absolute_match.group(2) or episode_min)
        return episode_min, episode_max

    absolute_range_match = _ABSOLUTE_RANGE_REGEX.search(raw_title)
    if absolute_range_match:
        return int(absolute_range_match.group(1)), int(absolute_range_match.group(2))

    dash_match = _TITLE_DASH_EP_REGEX.search(raw_title)
    if dash_match:
        episode_min = int(dash_match.group(1))
        episode_max = int(dash_match.group(2) or episode_min)
        return episode_min, episode_max

    standalone_match = _STANDALONE_EP_REGEX.search(raw_title)
    if standalone_match:
        episode_min = int(standalone_match.group(1))
        episode_max = int(standalone_match.group(2) or episode_min)
        return episode_min, episode_max

    if season is None:
        plain_range_match = re.search(r"\b(\d{2,4})\s*[-+]\s*(\d{2,4})\b", raw_title)
        if plain_range_match:
            return int(plain_range_match.group(1)), int(plain_range_match.group(2))

    return None, None


def _extract_series_title_from_raw_title(raw_title):
    title = _strip_file_extension(raw_title)
    title = re.sub(r"^\[[^\]]+\]\s*", "", title).strip()
    title = title.split("|", 1)[0].strip()
    title = re.sub(r"\[[^\]]+\]", " ", title)
    title = re.sub(
        r"\((?:[^)]*(?:multi|subs|audio|weekly|batch|eng dub|english dub|ger dub|german dub)[^)]*)\)",
        " ",
        title,
        flags=re.I,
    )

    title = re.sub(r"(?i)\b(?:Part|Teil)\s+\d+\b", "", title)

    match = (
        _SEASON_EP_REGEX.search(title)
        or _SEASON_DASH_EP_REGEX.search(title)
        or _ABSOLUTE_EP_REGEX.search(title)
        or _ABSOLUTE_RANGE_REGEX.search(title)
        or _TITLE_DASH_EP_REGEX.search(title)
        or _STANDALONE_EP_REGEX.search(title)
    )
    if match:
        title = title[: match.start()]

    title = re.sub(r"\s*\([^)]*\)\s*$", "", title)
    title = re.sub(r"\s*[-:|/._]+\s*$", "", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip()


def _extract_episode_title(raw_title):
    title = _strip_file_extension(raw_title)
    match = (
        _SEASON_EP_REGEX.search(title)
        or _SEASON_DASH_EP_REGEX.search(title)
        or _ABSOLUTE_EP_REGEX.search(title)
        or _ABSOLUTE_RANGE_REGEX.search(title)
        or _TITLE_DASH_EP_REGEX.search(title)
    )
    if not match:
        return None

    tail = title[match.end() :]
    if tail.lstrip().startswith(("[", "(")):
        return None
    tail = tail.split("|", 1)[0]
    tail = tail.split(" / ", 1)[0]
    tail = re.sub(r"^\s*[-:|/._]+\s*", "", tail)
    tail = re.sub(r"\[[^\]]+\]", " ", tail)
    tail = re.sub(r"^\s*\([^)]*\)\s*", "", tail)
    tail = re.sub(
        r"\((?:[^)]*(?:multi|subs|audio|weekly|batch|season|\|)[^)]*)\)",
        " ",
        tail,
        flags=re.I,
    )

    stop_match = _EPISODE_TITLE_STOP_REGEX.search(tail)
    if stop_match:
        tail = tail[: stop_match.start()]

    cleaned = re.sub(r"\s{2,}", " ", tail).strip(" -:|/._")
    if not cleaned or not re.search(r"[A-Za-z]", cleaned):
        return None

    return cleaned


def _extract_audio_langs(title_lower):
    audio_langs = []

    if "english dub" in title_lower or "eng dub" in title_lower:
        audio_langs.append("English")

    if "german dub" in title_lower or "ger dub" in title_lower:
        audio_langs.append("German")

    return audio_langs


def _extract_resolution(title_lower):
    if "2160p" in title_lower or "4k" in title_lower:
        return "2160p"
    if "1080p" in title_lower:
        return "1080p"
    if "720p" in title_lower:
        return "720p"
    if "480p" in title_lower:
        return "480p"
    return ""


def _extract_audio_codec(raw_title):
    for pattern, resolver in _AUDIO_CODEC_PATTERNS:
        match = pattern.search(raw_title)
        if match:
            return resolver(match)

    return ""


def _extract_video_codec(raw_title):
    if re.search(r"\bAV1\b", raw_title, re.I):
        return "AV1"
    if re.search(r"\bx265\b", raw_title, re.I):
        return "x265"
    if re.search(r"\bHEVC\b", raw_title, re.I):
        return "HEVC"
    if re.search(r"\bH[\s.]?265\b", raw_title, re.I):
        return "H265"
    if re.search(r"\bAVC\b", raw_title, re.I):
        return "AVC"
    if re.search(r"\bx264\b", raw_title, re.I):
        return "x264"
    if re.search(r"\bH[\s.]?264\b", raw_title, re.I):
        return "H264"
    if re.search(r"\bXVID\b", raw_title, re.I):
        return "Xvid"
    if re.search(r"\bMPEG\b", raw_title, re.I):
        return "MPEG"
    if re.search(r"\bVC-?1\b", raw_title, re.I):
        return "VC1"
    return ""


def _extract_source(title_lower):
    service = ""
    for pattern, label in _SOURCE_TAG_PATTERNS:
        if pattern.search(title_lower):
            service = label
            break

    source = ""
    if "webrip" in title_lower:
        source = "WEBRip"
    elif "web-dl" in title_lower or "webdl" in title_lower:
        source = "WEB-DL"
    elif re.search(r"\bweb\b", title_lower):
        source = "WEB"
    elif (
        "blu-ray" in title_lower
        or "bluray" in title_lower
        or re.search(r"\bbd\b", title_lower)
    ):
        source = "BluRay"
    elif "hdtv" in title_lower or "tvrip" in title_lower:
        source = "HDTV"

    if service and source:
        return f"{service}.{source}"
    if source:
        return source
    return service


def _extract_release_group(raw_title):
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", raw_title).strip()

    leading_match = re.match(r"^\[([^\]]+)\]", stripped)
    if leading_match:
        return _normalize_group_name(leading_match.group(1))

    trailing_match = re.search(r"-([A-Za-z0-9][A-Za-z0-9._-]*)$", stripped)
    if trailing_match:
        return _normalize_group_name(trailing_match.group(1))

    return ""


def _normalize_group_name(group_name):
    return re.sub(r"[^A-Za-z0-9]+", "", group_name or "")


def _extract_season_part(raw_title):
    match = _PART_REGEX.search(raw_title)
    if match:
        return int(match.group(1))
    return None


def _parse_listing_datetime(date_text):
    date_text = str(date_text or "").replace("Date/time submitted:", "").strip()
    if not date_text:
        return ""

    now = datetime.utcnow()
    lowered = date_text.lower()

    if lowered.startswith("today "):
        parsed = datetime.strptime(date_text[6:], "%H:%M")
        parsed = now.replace(
            hour=parsed.hour,
            minute=parsed.minute,
            second=0,
            microsecond=0,
        )
    elif lowered.startswith("yesterday "):
        parsed = datetime.strptime(date_text[10:], "%H:%M")
        parsed = (now - timedelta(days=1)).replace(
            hour=parsed.hour,
            minute=parsed.minute,
            second=0,
            microsecond=0,
        )
    else:
        parsed = datetime.strptime(date_text, "%d/%m/%Y %H:%M")

    return parsed.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _resolve_title_context(series_title, raw_title, release_info):
    raw_base_title = _extract_series_title_from_raw_title(raw_title)
    page_title = _clean_series_title(series_title) or raw_base_title or raw_title

    if (
        release_info.season is None
        and release_info.episode_min is None
        and raw_base_title
        and len(raw_base_title) > len(page_title)
    ):
        page_title = raw_base_title

    season_names = _get_cached_season_names(page_title)

    if not season_names:
        trailing_title, trailing_season = _resolve_trailing_season_context(page_title)
        if trailing_season is not None and (
            release_info.season is None or int(release_info.season) == trailing_season
        ):
            release_info.season = trailing_season
            return trailing_title, release_info

        if release_info.season is None:
            release_info.season = _extract_season_hint_from_title(page_title)
        return page_title, release_info

    canonical_title = season_names.get("all") or page_title
    if isinstance(canonical_title, list):
        canonical_title = canonical_title[0] if canonical_title else page_title

    resolved_season = release_info.season
    if resolved_season is None:
        resolved_season = _extract_season_hint_from_title(page_title)

    if resolved_season is None and release_info.episode_min is None:
        resolved_season = _match_xem_season(page_title, season_names)

    release_info.season = resolved_season
    if release_info.season is None:
        return page_title, release_info

    return str(canonical_title or page_title), release_info


def _match_xem_season(page_title, season_names):
    sanitized_page_title = sanitize_string(page_title)
    exact_match = None
    partial_matches = []

    for season_key, names_by_lang in season_names.items():
        if not str(season_key).isdigit():
            continue
        for names in names_by_lang.values():
            for name in names:
                sanitized_name = sanitize_string(name)
                if not sanitized_name:
                    continue
                if sanitized_page_title == sanitized_name:
                    exact_match = int(season_key)
                    break
                if (
                    sanitized_page_title in sanitized_name
                    or sanitized_name in sanitized_page_title
                ):
                    partial_matches.append((len(sanitized_name), int(season_key)))
            if exact_match is not None:
                break
        if exact_match is not None:
            break

    if exact_match is not None:
        return exact_match

    if partial_matches:
        partial_matches.sort(reverse=True)
        return partial_matches[0][1]

    return None


@lru_cache(maxsize=256)
def _get_cached_season_names(page_title):
    try:
        return get_all_season_names(page_title)
    except Exception:
        return None
