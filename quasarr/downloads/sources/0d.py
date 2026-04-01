# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import info


class Source(AbstractDownloadSource):
    initials = "0d"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        requested_mirrors = {
            _normalize_mirror_name(mirror) for mirror in (mirrors or []) if mirror
        }
        host = shared_state.values["config"]("Hostnames").get(Source.initials)
        headers = {"User-Agent": shared_state.values["user_agent"]}
        session = requests.Session()

        links = []
        errors = []

        page_soup = _fetch_soup(session, url, headers)
        if page_soup is None:
            errors.append(f"Failed to fetch release page: {url}")
        else:
            links.extend(_extract_links_from_soup(page_soup, requested_mirrors))

        if not links and host:
            search_url = f"https://{host}/search?q={quote_plus(title)}"
            search_soup = _fetch_soup(session, search_url, headers)
            if search_soup is None:
                errors.append(f"Failed to fetch search page: {search_url}")
            else:
                card = _find_matching_card(search_soup, url, title)
                if card:
                    links.extend(_extract_links_from_soup(card, requested_mirrors))
                else:
                    links.extend(
                        _extract_links_from_soup(search_soup, requested_mirrors)
                    )

        links = _dedupe_links(links)

        if links:
            clear_hostname_issue(Source.initials)
            return {"links": links}

        if errors:
            mark_hostname_issue(Source.initials, "download", errors[-1])
        info(f"No external download links found on OD page for {title}")
        return {"links": []}


def _fetch_soup(session, url, headers):
    try:
        response = session.get(
            url,
            headers=headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except Exception:
        return None


def _find_matching_card(soup, target_url, target_title):
    cards = soup.select("div.card[data-href]")
    if not cards:
        return None

    for card in cards:
        card_url = (card.get("data-href") or "").strip()
        if card_url and _urls_match(card_url, target_url):
            return card

    wanted_title = _normalize_title(target_title)
    if wanted_title:
        for card in cards:
            card_title = _extract_card_title(card)
            if _normalize_title(card_title) == wanted_title:
                return card
        for card in cards:
            card_title = _normalize_title(_extract_card_title(card))
            if card_title and (
                card_title in wanted_title or wanted_title in card_title
            ):
                return card

    return cards[0]


def _extract_card_title(card):
    title_node = card.find("h2")
    if not title_node:
        return ""
    return title_node.get_text(" ", strip=True)


def _extract_links_from_soup(soup, requested_mirrors):
    links = []
    for anchor in soup.select(
        "a[href*='hide.'][href*='/container/'], a[href*='hide.'][href*='/folder/']"
    ):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue

        mirror = _extract_mirror_name(anchor, href)
        normalized_mirror = _normalize_mirror_name(mirror)
        if requested_mirrors and normalized_mirror not in requested_mirrors:
            continue

        links.append([href, mirror or normalized_mirror or "unknown"])
    return links


def _extract_mirror_name(anchor, href):
    for node in anchor.select("span"):
        text = node.get_text(" ", strip=True)
        if text:
            return text

    anchor_text = anchor.get_text(" ", strip=True)
    if anchor_text:
        return anchor_text

    return _normalize_mirror_name(href)


def _normalize_mirror_name(value):
    normalized = (value or "").lower().strip()
    if not normalized:
        return ""

    if "://" in normalized:
        parsed = urlparse(normalized)
        normalized = parsed.netloc or parsed.path

    if normalized.startswith("www."):
        normalized = normalized[4:]

    normalized = normalized.split("/", 1)[0]
    normalized = normalized.split(":", 1)[0]
    normalized = normalized.replace("-", " ").strip()
    normalized = normalized.split()[-1] if " " in normalized else normalized

    if "." in normalized:
        normalized = normalized.split(".", 1)[0]

    aliases = {
        "ddl": "ddownload",
        "ddlto": "ddownload",
        "rg": "rapidgator",
    }
    return aliases.get(normalized, normalized)


def _normalize_title(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _urls_match(left, right):
    left = (left or "").rstrip("/").lower()
    right = (right or "").rstrip("/").lower()
    return left == right


def _dedupe_links(links):
    deduped = []
    seen = set()
    for href, mirror in links:
        key = href.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append([href, mirror])
    return deduped
