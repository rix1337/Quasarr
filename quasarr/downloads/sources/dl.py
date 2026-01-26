# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

from bs4 import BeautifulSoup, NavigableString

from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.sessions.dl import (
    fetch_via_requests_session,
    invalidate_session,
    retrieve_and_validate_session,
)
from quasarr.providers.utils import check_links_online_status, generate_status_url

hostname = "dl"

# Common TLDs to strip for mirror name comparison
COMMON_TLDS = {
    ".com",
    ".net",
    ".io",
    ".cc",
    ".to",
    ".me",
    ".org",
    ".co",
    ".de",
    ".eu",
    ".info",
}


def normalize_mirror_name(name):
    """
    Normalize mirror name for comparison by lowercasing and removing TLDs.
    e.g., "DDownload.com" -> "ddownload", "Rapidgator.net" -> "rapidgator"
    """
    if not name:
        return ""
    normalized = name.lower().strip()
    for tld in COMMON_TLDS:
        if normalized.endswith(tld):
            normalized = normalized[: -len(tld)]
            break
    return normalized


def extract_password_from_post(soup, host):
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


def extract_mirror_name_from_link(link_element):
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
    known_hosters = {
        "rapidgator": ["rapidgator", "rg"],
        "ddownload": ["ddownload", "ddl"],
        "turbobit": ["turbobit"],
        "1fichier": ["1fichier"],
    }

    # Skip if link text is a URL
    if link_text and len(link_text) > 2 and not link_text.startswith("http"):
        cleaned = re.sub(r"[^\w\s-]", "", link_text).strip().lower()
        if cleaned and cleaned not in common_non_hosters:
            main_part = cleaned.split()[0] if " " in cleaned else cleaned
            if 2 < len(main_part) < 30:
                return main_part

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
                            return mirror
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
            for hoster, patterns in known_hosters.items():
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
                return cleaned.split()[0] if " " in cleaned else cleaned

    return None


def extract_status_url_from_html(link_element, crypter_type):
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


def build_filecrypt_status_map(soup):
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

        if mirror_name and mirror_name not in status_map:
            status_map[mirror_name] = status_url
            debug(f"Mapped status image for mirror: {mirror_name} -> {status_url}")

    return status_map


def extract_links_and_password_from_post(post_content, host):
    """
    Extract download links and password from a forum post.
    Returns links with status URLs for online checking.
    """
    links = []  # [href, identifier, status_url]
    soup = BeautifulSoup(post_content, "html.parser")

    # Build status map for FileCrypt links (handles separated status images)
    filecrypt_status_map = build_filecrypt_status_map(soup)

    for link in soup.find_all("a", href=True):
        href = link.get("href")

        if href.startswith("/") or host in href:
            continue

        if re.search(r"filecrypt\.", href, re.IGNORECASE):
            crypter_type = "filecrypt"
        elif re.search(r"hide\.", href, re.IGNORECASE):
            crypter_type = "hide"
        elif re.search(r"keeplinks\.", href, re.IGNORECASE):
            crypter_type = "keeplinks"
        elif re.search(r"tolink\.", href, re.IGNORECASE):
            crypter_type = "tolink"
        else:
            debug(f"Unsupported link crypter/hoster found: {href}")
            continue

        mirror_name = extract_mirror_name_from_link(link)
        identifier = mirror_name if mirror_name else crypter_type

        # Get status URL - try extraction first, then status map, then generation
        status_url = extract_status_url_from_html(link, crypter_type)

        if not status_url and crypter_type == "filecrypt" and mirror_name:
            # Try to find in status map by mirror name (normalized, case-insensitive, TLD-stripped)
            mirror_normalized = normalize_mirror_name(mirror_name)
            for map_key, map_url in filecrypt_status_map.items():
                map_key_normalized = normalize_mirror_name(map_key)
                if (
                    mirror_normalized in map_key_normalized
                    or map_key_normalized in mirror_normalized
                ):
                    status_url = map_url
                    break

        if not status_url:
            status_url = generate_status_url(href, crypter_type)

        # Avoid duplicates (check href and identifier)
        if not any(l[0] == href and l[1] == identifier for l in links):
            links.append([href, identifier, status_url])
            status_info = f"status: {status_url}" if status_url else "no status URL"
            if mirror_name:
                debug(
                    f"Found {crypter_type} link for mirror: {mirror_name} ({status_info})"
                )
            else:
                debug(f"Found {crypter_type} link ({status_info})")

    password = ""
    if links:
        password = extract_password_from_post(soup, host)

    return links, password


def get_dl_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    DL source handler - extracts links and password from forum thread.
    Iterates through posts to find one with online links.

    Note: The password parameter is unused intentionally - password must be extracted from the post.
    """

    host = shared_state.values["config"]("Hostnames").get(hostname)

    sess = retrieve_and_validate_session(shared_state)
    if not sess:
        info(f"Could not retrieve valid session for {host}")
        mark_hostname_issue(hostname, "download", "Session error")
        return {"links": [], "password": ""}

    try:
        response = fetch_via_requests_session(
            shared_state, method="GET", target_url=url, timeout=30
        )

        if response.status_code != 200:
            info(f"Failed to load thread page: {url} (Status: {response.status_code})")
            return {"links": [], "password": ""}

        soup = BeautifulSoup(response.text, "html.parser")

        # Get all posts in thread
        posts = soup.select("article.message--post")
        if not posts:
            info(f"Could not find any posts in thread: {url}")
            return {"links": [], "password": ""}

        # Track first post with unverifiable links as fallback
        fallback_links = None
        fallback_password = ""

        # Iterate through posts to find one with verified online links
        for post_index, post in enumerate(posts):
            post_content = post.select_one("div.bbWrapper")
            if not post_content:
                continue

            links_with_status, extracted_password = (
                extract_links_and_password_from_post(str(post_content), host)
            )

            if not links_with_status:
                continue

            # Check if any links have status URLs we can verify
            has_verifiable_links = any(link[2] for link in links_with_status)

            if not has_verifiable_links:
                # No way to check online status - save as fallback and continue looking
                if fallback_links is None:
                    fallback_links = [[link[0], link[1]] for link in links_with_status]
                    fallback_password = extracted_password
                    debug(
                        f"Post #{post_index + 1} has links but no status URLs, saving as fallback..."
                    )
                continue

            # Check which links are online
            online_links = check_links_online_status(links_with_status, shared_state)

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
            hostname, "download", str(e) if "e" in dir() else "Download error"
        )
        invalidate_session(shared_state)
        return {"links": [], "password": ""}
