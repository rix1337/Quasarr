# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from quasarr.constants import (
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, info
from quasarr.providers.utils import (
    convert_to_mb,
    generate_download_link,
    is_imdb_id,
    is_valid_release,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "0d"
    supports_imdb = True
    supports_phrase = False
    supported_categories = [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS]

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        return []

    def search(
        self,
        shared_state: shared_state,
        start_time: float,
        search_category: str,
        search_string: str = "",
        season: int = None,
        episode: int = None,
    ) -> list[SearchRelease]:
        releases = []
        host = shared_state.values["config"]("Hostnames").get(self.initials)
        if not host:
            return releases

        imdb_id = is_imdb_id(search_string)
        if not imdb_id:
            return releases

        parsed_season = _to_optional_int(season)
        parsed_episode = _to_optional_int(episode)

        include_year = _is_movie_search(search_category)
        queries = _build_queries(
            shared_state,
            imdb_id,
            parsed_season,
            parsed_episode,
            include_year=include_year,
        )
        if not queries:
            info(f"{self.initials.upper()}: no title for IMDb {imdb_id}")
            return releases

        headers = {"User-Agent": shared_state.values["user_agent"]}
        try:
            cards = _load_cards(host, headers, queries)
        except Exception as e:
            info(f"{self.initials.upper()}: search load error: {e}")
            mark_hostname_issue(self.initials, "search", str(e))
            return releases

        for card in cards:
            try:
                title = _extract_title(card)
                if not title:
                    continue

                if not is_valid_release(
                    title, search_category, search_string, parsed_season, parsed_episode
                ):
                    continue

                source = _extract_source_url(card, host)
                if not source:
                    continue

                size_item = _extract_size_item(card)
                mb = convert_to_mb(size_item)
                size = mb * 1024 * 1024
                published = _extract_published_date(card)

                link = generate_download_link(
                    shared_state,
                    title,
                    source,
                    mb,
                    "",
                    imdb_id,
                    self.initials,
                )

                releases.append(
                    {
                        "details": {
                            "title": title,
                            "hostname": self.initials,
                            "imdb_id": imdb_id,
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": source,
                        },
                        "type": "protected",
                    }
                )
            except Exception as e:
                debug(f"{self.initials.upper()}: error parsing search result: {e}")

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s ({self.initials.upper()})")
        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _build_queries(
    shared_state: shared_state,
    imdb_id: str,
    season: int | None,
    episode: int | None,
    include_year: bool = False,
) -> list[str]:
    base_titles = []
    for lang in ("de", "en"):
        title = get_localized_title(shared_state, imdb_id, lang)
        if not title:
            continue
        title = unescape(title).strip()
        if title:
            base_titles.append(title)

    suffix = ""
    if season is not None:
        suffix = f" S{int(season):02d}"
        if episode is not None:
            suffix += f"E{int(episode):02d}"

    year = str(get_year(imdb_id) or "").strip() if include_year else ""

    queries = []
    seen = set()
    for title in base_titles:
        query = f"{title}{suffix}".strip()
        if year and year not in query:
            query = f"{query} {year}".strip()

        query = re.sub(r"\s+", ".", query)
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)
    return queries


def _to_optional_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    value_str = str(value).strip()
    if not value_str:
        return None
    if not value_str.isdigit():
        return None
    return int(value_str)


def _is_movie_search(search_category) -> bool:
    try:
        category = int(search_category)
    except Exception:
        return False
    return category // 1000 * 1000 == SEARCH_CAT_MOVIES


def _load_cards(host: str, headers: dict, queries: list[str]):
    all_cards = []
    seen = set()
    last_error = None
    had_success = False

    search_url = f"https://{host}/search"
    for query in queries:
        try:
            full_search_url = (
                requests.Request("GET", search_url, params={"q": query}).prepare().url
            )
            debug(f"0D search URL: {full_search_url}")

            response = requests.get(
                search_url,
                params={"q": query},
                headers=headers,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            had_success = True
            soup = BeautifulSoup(response.content, "html.parser")

            for card in soup.select("div.card[data-href]"):
                href = (card.get("data-href") or "").strip()
                title = _extract_title(card)
                key = (href.lower(), title.lower())
                if key in seen:
                    continue
                seen.add(key)
                all_cards.append(card)
        except Exception as e:
            last_error = e

    if all_cards:
        return all_cards
    if had_success:
        return []
    if last_error:
        raise last_error
    raise RuntimeError("No valid search query")


def _extract_title(card) -> str:
    title_node = card.find("h2")
    if not title_node:
        return ""
    return title_node.get_text(" ", strip=True)


def _extract_source_url(card, host: str) -> str:
    href = (card.get("data-href") or "").strip()
    if not href:
        return ""
    return urljoin(f"https://{host}", href)


def _extract_size_item(card) -> dict:
    text = card.get_text(" ", strip=True)
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|MB|KB)\b", text, re.IGNORECASE)
    if not match:
        return {"size": "0", "sizeunit": "MB"}
    return {"size": match.group(1).replace(",", "."), "sizeunit": match.group(2)}


def _extract_published_date(card) -> str:
    for span in card.find_all("span"):
        text = span.get_text(" ", strip=True)
        if not text:
            continue
        if "ago" in text.lower() or text.lower().startswith("vor "):
            return _convert_relative_to_rss_date(text)
    return ""


def _convert_relative_to_rss_date(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return ""
    if text in {"just now", "gerade eben"}:
        dt = datetime.utcnow()
        return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

    match = re.search(r"(\d+)\s+([a-zA-Z]+)", text)
    if not match:
        return ""

    count = int(match.group(1))
    unit = match.group(2)
    delta = _to_timedelta(count, unit)
    if delta is None:
        return ""

    dt = datetime.utcnow() - delta
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _to_timedelta(count: int, unit: str) -> timedelta | None:
    normalized = unit.lower().rstrip("s")
    if normalized.startswith(("sekunde", "second")):
        return timedelta(seconds=count)
    if normalized.startswith(("minute", "min")):
        return timedelta(minutes=count)
    if normalized.startswith(("stunde", "hour")):
        return timedelta(hours=count)
    if normalized.startswith(("tag", "day")):
        return timedelta(days=count)
    if normalized.startswith(("woche", "week")):
        return timedelta(weeks=count)
    if normalized.startswith(("monat", "month")):
        return timedelta(days=30 * count)
    if normalized.startswith(("jahr", "year")):
        return timedelta(days=365 * count)
    return None
