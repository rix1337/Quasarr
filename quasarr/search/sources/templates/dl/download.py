# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS, SHARE_HOSTERS_LOWERCASE
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.sessions.dl import (
    fetch_via_requests_session,
    invalidate_session,
    retrieve_and_validate_session,
)
from quasarr.providers.utils import check_links_online_status, generate_status_url

_PLAINTEXT_URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_TRAILING_URL_CHARS = ".,;:)]}"


class Source(AbstractDownloadSource):
    initials = "dl"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        """
        DL source handler - extracts links and password from forum thread.
        Iterates through posts to find one with online links.
        """
        requested_mirrors = {
            _normalize_mirror_name(mirror) for mirror in (mirrors or []) if mirror
        }

        host = shared_state.values["config"]("Hostnames").get(Source.initials)

        sess = retrieve_and_validate_session(shared_state)
        if not sess:
            info(f"Could not retrieve valid session for {host}")
            mark_hostname_issue(Source.initials, "download", "Session error")
            return {"links": [], "password": ""}

        try:
            response = fetch_via_requests_session(
                shared_state,
                method="GET",
                target_url=url,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                info(
                    f"Failed to load thread page: {url} (Status: {response.status_code})"
                )
                return {"links": [], "password": ""}

            soup = BeautifulSoup(response.text, "html.parser")

            # Get all posts in thread
            posts = soup.select("article.message--post")
            if not posts:
                info(f"Could not find any posts in thread: {url}")
                return {"links": [], "password": ""}
            posts = _posts_matching_requested_fragment(posts, url)

            # Track first post with unverifiable links as fallback
            fallback_links = None
            fallback_password = ""

            # Iterate through posts to find one with verified online links
            for post_index, post in enumerate(posts):
                post_content = post.select_one("div.bbWrapper")
                if not post_content:
                    continue

                links_with_status, extracted_password = (
                    _extract_links_and_password_from_post(
                        str(post_content), host, requested_mirrors
                    )
                )

                if not links_with_status:
                    continue

                # Check if any links have status URLs we can verify
                has_verifiable_links = any(link[2] for link in links_with_status)

                if not has_verifiable_links:
                    # No way to check online status - save as fallback and continue looking
                    if fallback_links is None:
                        fallback_links = [
                            [link[0], link[1]] for link in links_with_status
                        ]
                        fallback_password = extracted_password
                        debug(
                            f"Post #{post_index + 1} has links but no status URLs, saving as fallback..."
                        )
                    continue

                # Check which links are online
                online_links = check_links_online_status(
                    links_with_status, shared_state
                )

                if online_links:
                    post_info = (
                        "first post" if post_index == 0 else f"post #{post_index + 1}"
                    )
                    debug(
                        f"Found {len(online_links)} verified online link(s) in {post_info} for: {title}"
                    )
                    return {"links": online_links, "password": extracted_password}
                else:
                    debug(
                        f"All links in post #{post_index + 1} are offline, checking next post..."
                    )

            # No verified online links found - return fallback if available
            if fallback_links:
                debug(
                    f"No verified online links found, returning unverified fallback links for: {title}"
                )
                return {"links": fallback_links, "password": fallback_password}

            info(f"No online download links found in any post: {url}")
            return {"links": [], "password": ""}

        except Exception as e:
            info(f"Error extracting download links from {url}: {e}")
            mark_hostname_issue(
                Source.initials,
                "download",
                str(e) if "e" in dir() else "Download error",
            )
            invalidate_session(shared_state)
            return {"links": [], "password": ""}


def _posts_matching_requested_fragment(posts, url):
    fragment = urlparse(url).fragment
    if not fragment:
        return posts

    normalized_fragment = _normalize_post_fragment(fragment)
    return [post for post in posts if _post_matches_fragment(post, normalized_fragment)]


def _post_matches_fragment(post, normalized_fragment):
    candidates = {
        _normalize_post_fragment(post.get("id")),
        _normalize_post_fragment(post.get("data-content")),
    }

    return normalized_fragment in candidates


def _normalize_post_fragment(fragment):
    normalized = str(fragment or "").strip().lstrip("#").lower()
    normalized = re.sub(r"^js-", "", normalized)
    return normalized


def _normalize_mirror_name(name):
    """
    Normalize mirror/provider names to a provider root token.
    Works with plain names, hostnames, and URLs regardless of TLD.
    """
    if not name:
        return ""

    normalized = str(name).lower().strip()

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

    # Handle alternative spellings/shorthands
    if normalized in ["rg"]:
        return "rapidgator"
    if normalized in ["ddl", "ddlto"]:
        return "ddownload"

    return normalized


def _extract_password_from_post(soup, host):
    """
    Extract password from forum post using multiple strategies.
    Returns empty string if no password found or if explicitly marked as 'no password'.
    """
    post_text = soup.get_text()
    post_text = re.sub(r"\s+", " ", post_text).strip()

    password_pattern = r"(?:passwort|password|pass|pw)[\s:]+([a-zA-Z0-9._-]{2,50})"
    match = re.search(password_pattern, post_text, re.IGNORECASE)

    if match:
        password = match.group(1).strip()
        if not re.match(
            r"^(?:download|mirror|link|episode|info|mediainfo|spoiler|hier|click|klick|kein|none|no)",
            password,
            re.IGNORECASE,
        ):
            debug(f"Found password: {password}")
            return password

    no_password_patterns = [
        r"(?:passwort|password|pass|pw)[\s:]*(?:kein(?:es)?|none|no|nicht|not|nein|-|–|—)",
        r"(?:kein(?:es)?|none|no|nicht|not|nein)\s*(?:passwort|password|pass|pw)",
    ]

    for pattern in no_password_patterns:
        if re.search(pattern, post_text, re.IGNORECASE):
            debug("No password required (explicitly stated)")
            return ""

    default_password = f"www.{host}"
    debug(f"No password found, using default: {default_password}")
    return default_password


def _extract_mirror_name_from_link(link_element):
    """
    Extract the mirror/hoster name from the link text or nearby text.
    """
    link_text = link_element.get_text(strip=True)
    common_non_hosters = {
        "download",
        "mirror",
        "link",
        "hier",
        "click",
        "klick",
        "code",
        "spoiler",
    }

    # Known hoster patterns for image detection
    # Maps patterns to normalized names in SHARE_HOSTERS
    hoster_patterns = {
        "rapidgator": ["rapidgator", "rg"],
        "ddownload": ["ddownload", "ddl"],
        "turbobit": ["turbobit"],
        "1fichier": ["1fichier"],
    }

    # Skip if link text is a URL
    if link_text and len(link_text) > 2 and not link_text.startswith("http"):
        # Forum labels may include a generic action and a hoster domain, e.g.
        # "Download via Rapidgator.net". Normalize each label token so URL
        # punctuation and aliases use the same canonical names as filters.
        for token in link_text.split():
            normalized_token = _normalize_mirror_name(token)
            if normalized_token in SHARE_HOSTERS_LOWERCASE:
                return normalized_token

        cleaned = re.sub(r"[^\w\s-]", "", link_text).strip().lower()
        if cleaned and cleaned not in common_non_hosters:
            main_part = cleaned.split()[0] if " " in cleaned else cleaned
            if 2 < len(main_part) < 30:
                return _normalize_mirror_name(main_part)

    # Check previous siblings including text nodes
    for sibling in link_element.previous_siblings:
        # Handle text nodes (NavigableString)
        if isinstance(sibling, NavigableString):
            text = sibling.strip()
            if text:
                # Remove common separators like @ : -
                cleaned = re.sub(r"[@:\-–—\s]+$", "", text).strip().lower()
                cleaned = re.sub(r"[^\w\s.-]", "", cleaned).strip()
                if cleaned and len(cleaned) > 2 and cleaned not in common_non_hosters:
                    # Take the last word as mirror name (e.g., "Rapidgator" from "Rapidgator @")
                    parts = cleaned.split()
                    if parts:
                        mirror = parts[-1]
                        if 2 < len(mirror) < 30:
                            return _normalize_mirror_name(mirror)
            continue

        # Skip non-Tag elements
        if not hasattr(sibling, "name") or sibling.name is None:
            continue

        # Skip spoiler elements entirely
        classes = sibling.get("class", [])
        if classes and any("spoiler" in str(c).lower() for c in classes):
            continue

        # Check for images with hoster names in src/alt/data-url
        img = sibling.find("img") if sibling.name != "img" else sibling
        if img:
            img_identifiers = (
                img.get("src", "") + img.get("alt", "") + img.get("data-url", "")
            ).lower()
            for hoster, patterns in hoster_patterns.items():
                if any(pattern in img_identifiers for pattern in patterns):
                    return hoster

        sibling_text = sibling.get_text(strip=True).lower()
        # Skip if text is too long - likely NFO content or other non-mirror text
        if len(sibling_text) > 30:
            continue
        if (
            sibling_text
            and len(sibling_text) > 2
            and sibling_text not in common_non_hosters
        ):
            cleaned = re.sub(r"[^\w\s-]", "", sibling_text).strip()
            if cleaned and 2 < len(cleaned) < 30:
                mirror = cleaned.split()[0] if " " in cleaned else cleaned
                return _normalize_mirror_name(mirror)

    return None


def _extract_status_url_from_html(link_element, crypter_type):
    """
    Extract status image URL from HTML near the link element.
    Used primarily for FileCrypt where status URLs cannot be generated.
    """
    if crypter_type != "filecrypt":
        return None

    # Look for status image in the link itself
    img = link_element.find("img")
    if img:
        for attr in ["src", "data-url"]:
            url = img.get(attr, "")
            if "filecrypt.cc/Stat/" in url:
                return url

    # Look in siblings
    for sibling in link_element.next_siblings:
        if not hasattr(sibling, "name") or sibling.name is None:
            continue
        if sibling.name == "img":
            for attr in ["src", "data-url"]:
                url = sibling.get(attr, "")
                if "filecrypt.cc/Stat/" in url:
                    return url
        # Check nested images
        nested_img = sibling.find("img") if hasattr(sibling, "find") else None
        if nested_img:
            for attr in ["src", "data-url"]:
                url = nested_img.get(attr, "")
                if "filecrypt.cc/Stat/" in url:
                    return url
        # Stop at next link
        if sibling.name == "a":
            break

    return None


def _detect_supported_crypter(href):
    if re.search(r"filecrypt\.", href, re.IGNORECASE):
        return "filecrypt"
    if re.search(r"hide\.", href, re.IGNORECASE):
        return "hide"
    if re.search(r"keeplinks\.", href, re.IGNORECASE):
        return "keeplinks"
    if re.search(r"tolink\.", href, re.IGNORECASE):
        return "tolink"
    return None


def _detect_direct_hoster(href):
    parsed = urlparse(href)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    hoster = _normalize_mirror_name(host)
    if hoster in SHARE_HOSTERS_LOWERCASE:
        return hoster

    return None


def _build_filecrypt_status_map(soup):
    """
    Build a map of mirror names to FileCrypt status URLs.
    Handles cases where status images are in a separate section from links.
    Returns dict: {mirror_name_lowercase: status_url}
    """
    status_map = {}

    # Find all FileCrypt status images in the post
    for img in soup.find_all("img"):
        status_url = None
        for attr in ["src", "data-url"]:
            url = img.get(attr, "")
            if "filecrypt.cc/Stat/" in url:
                status_url = url
                break

        if not status_url:
            continue

        # Look for associated mirror name in previous text/siblings
        mirror_name = None

        # Check parent's previous siblings and text nodes
        parent = img.parent
        if parent:
            # Get all previous text content before this image
            prev_text = ""
            for prev in parent.previous_siblings:
                if hasattr(prev, "get_text"):
                    prev_text = prev.get_text(strip=True)
                elif isinstance(prev, NavigableString):
                    prev_text = prev.strip()
                if prev_text:
                    break

            # Also check text directly before within parent
            for prev in img.previous_siblings:
                if isinstance(prev, NavigableString) and prev.strip():
                    prev_text = prev.strip()
                    break
                elif hasattr(prev, "get_text"):
                    text = prev.get_text(strip=True)
                    if text:
                        prev_text = text
                        break

            if prev_text:
                # Clean up the text to get mirror name
                cleaned = re.sub(r"[^\w\s.-]", "", prev_text).strip().lower()
                # Take last word/phrase as it's likely the mirror name
                parts = cleaned.split()
                if parts:
                    mirror_name = parts[-1] if len(parts[-1]) > 2 else cleaned

        if mirror_name:
            mirror_normalized = _normalize_mirror_name(mirror_name)
            if mirror_normalized not in status_map:
                status_map[mirror_normalized] = status_url
                debug(
                    f"Mapped status image for mirror: {mirror_normalized} -> {status_url}"
                )

    return status_map


def _clean_plaintext_url(url):
    return str(url or "").strip().rstrip(_TRAILING_URL_CHARS)


def _extract_mirror_name_from_text(text):
    """
    Extract a known mirror label from visible text near plaintext URLs.
    """
    text_without_urls = _PLAINTEXT_URL_RE.sub(" ", str(text or ""))
    candidates = re.findall(r"[a-zA-Z0-9]+", text_without_urls)

    for candidate in reversed(candidates):
        normalized = _normalize_mirror_name(candidate)
        if normalized in SHARE_HOSTERS_LOWERCASE:
            return normalized

    normalized_text = _normalize_mirror_name(text_without_urls)
    if normalized_text in SHARE_HOSTERS_LOWERCASE:
        return normalized_text

    return None


def _iter_plaintext_download_links(soup):
    """
    Yield downloadable URLs rendered as text, preserving the last hoster heading.
    """
    current_mirror = None

    for text_node in soup.find_all(string=True):
        parent = getattr(text_node, "parent", None)
        if parent and (parent.name == "a" or parent.find_parent("a")):
            continue

        text = str(text_node)
        search_start = 0
        matched_url = False

        for match in _PLAINTEXT_URL_RE.finditer(text):
            matched_url = True
            prefix_mirror = _extract_mirror_name_from_text(
                text[search_start : match.start()]
            )
            if prefix_mirror:
                current_mirror = prefix_mirror

            href = _clean_plaintext_url(match.group(0))
            crypter_type = _detect_supported_crypter(href)
            if crypter_type or _detect_direct_hoster(href):
                yield href, crypter_type, current_mirror

            search_start = match.end()

        suffix = text[search_start:] if matched_url else text
        suffix_mirror = _extract_mirror_name_from_text(suffix)
        if suffix_mirror:
            current_mirror = suffix_mirror


def _extract_links_and_password_from_post(post_content, host, requested_mirrors=None):
    """
    Extract download links and password from a forum post.
    Returns links with status URLs for online checking.
    """
    links = []  # [href, identifier, status_url]
    soup = BeautifulSoup(post_content, "html.parser")

    # Build status map for FileCrypt links (handles separated status images)
    filecrypt_status_map = _build_filecrypt_status_map(soup)

    def add_link(href, crypter_type, mirror_name=None, link_element=None):
        if href.startswith("/") or host in href:
            return

        direct_hoster = None
        if not crypter_type:
            direct_hoster = _detect_direct_hoster(href)
        if not crypter_type and not direct_hoster:
            debug(f"Unsupported link crypter/hoster found: {href}")
            return

        normalized_mirror = (
            direct_hoster
            if direct_hoster
            else _normalize_mirror_name(mirror_name)
            if mirror_name
            else None
        )

        if requested_mirrors and normalized_mirror:
            if normalized_mirror not in requested_mirrors:
                return

        identifier = normalized_mirror if normalized_mirror else crypter_type

        # Get status URL - try extraction first, then status map, then generation
        status_url = None
        if crypter_type:
            status_url = (
                _extract_status_url_from_html(link_element, crypter_type)
                if link_element
                else None
            )

        if not status_url and crypter_type == "filecrypt" and normalized_mirror:
            # Try to find in status map by mirror name (normalized, case-insensitive, TLD-stripped)
            for map_key, map_url in filecrypt_status_map.items():
                if (
                    normalized_mirror in map_key
                    or map_key in normalized_mirror
                    or normalized_mirror in SHARE_HOSTERS_LOWERCASE
                    and map_key in SHARE_HOSTERS_LOWERCASE
                    and normalized_mirror == map_key
                ):
                    status_url = map_url
                    break

        if not status_url and crypter_type:
            status_url = generate_status_url(href, crypter_type)

        # Avoid duplicates (check href and identifier)
        if not any(l[0] == href and l[1] == identifier for l in links):
            links.append([href, identifier, status_url])
            status_info = f"status: {status_url}" if status_url else "no status URL"
            link_type = crypter_type or "direct"
            if mirror_name:
                debug(
                    f"Found {link_type} link for mirror: {mirror_name} ({status_info})"
                )
            else:
                debug(f"Found {link_type} link ({status_info})")

    for link in soup.find_all("a", href=True):
        href = link.get("href")
        crypter_type = _detect_supported_crypter(href)
        add_link(
            href,
            crypter_type,
            mirror_name=_extract_mirror_name_from_link(link),
            link_element=link,
        )

    for href, crypter_type, mirror_name in _iter_plaintext_download_links(soup):
        add_link(href, crypter_type, mirror_name=mirror_name)

    password = ""
    if links:
        password = _extract_password_from_post(soup, host)

    return links, password
