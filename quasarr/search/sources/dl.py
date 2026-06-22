# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from datetime import datetime
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from quasarr.constants import (
    CODEC_REGEX,
    FEED_REQUEST_TIMEOUT_SECONDS,
    RESOLUTION_REGEX,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
    SHARE_HOSTERS_LOWERCASE,
    XXX_REGEX,
)
from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.imdb_metadata import get_localized_title, get_year
from quasarr.providers.log import debug, info, trace, warn
from quasarr.providers.sessions.dl import (
    fetch_via_requests_session,
    invalidate_session,
    retrieve_and_validate_session,
)
from quasarr.providers.utils import (
    generate_download_link,
    get_base_search_category_id,
    is_imdb_id,
    is_valid_release,
    replace_umlauts,
)
from quasarr.search.sources.helpers.search_release import SearchRelease
from quasarr.search.sources.helpers.search_source import AbstractSearchSource


class Source(AbstractSearchSource):
    initials = "dl"
    language = "de"
    requires_account = True
    supports_imdb = True
    supports_phrase = True
    supported_categories = [
        SEARCH_CAT_MOVIES,
        SEARCH_CAT_SHOWS,
        SEARCH_CAT_MUSIC,
        SEARCH_CAT_BOOKS,
    ]
    requires_login = True

    def feed(
        self, shared_state: shared_state, start_time: float, search_category: str
    ) -> list[SearchRelease]:
        """
        Parse the correct forum and return releases.
        """
        releases = []
        host = shared_state.values["config"]("Hostnames").get(self.initials)

        base_search_category = get_base_search_category_id(search_category)

        if base_search_category == SEARCH_CAT_BOOKS:
            forum = "magazine-zeitschriften.72"
        elif base_search_category == SEARCH_CAT_MOVIES:
            forum = "hd.8"
        elif base_search_category == SEARCH_CAT_SHOWS:
            forum = "hd.14"
        elif base_search_category == SEARCH_CAT_MUSIC:
            forum = "alben.42"
        else:
            warn(f"Unknown search category: {search_category}")
            return releases

        if not host:
            debug("hostname not configured")
            return releases

        try:
            sess = retrieve_and_validate_session(shared_state)
            if not sess:
                warn(f"Could not retrieve valid session for {host}")
                return releases

            forum_url = (
                f"https://www.{host}/forums/{forum}/?order=post_date&direction=desc"
            )
            r = sess.get(forum_url, timeout=FEED_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()

            soup = BeautifulSoup(r.content, "html.parser")

            # Find all thread items in the forum
            items = soup.select("div.structItem.structItem--thread")

            if not items:
                debug("No entries found in Forum")
                return releases

            for item in items:
                try:
                    # Extract title from the thread
                    title_elem = item.select_one("div.structItem-title a")
                    if not title_elem:
                        continue

                    title = "".join(title_elem.strings)
                    if not title:
                        continue

                    title = unescape(title)
                    title = _normalize_title_for_arr(title)

                    # Extract thread URL
                    thread_url = title_elem.get("href")
                    if not thread_url:
                        continue

                    # Make sure URL is absolute
                    if thread_url.startswith("/"):
                        thread_url = f"https://www.{host}{thread_url}"

                    # Extract date and convert to RFC 2822 format
                    date_elem = item.select_one("time.u-dt")
                    iso_date = date_elem.get("datetime", "") if date_elem else ""
                    published = _convert_to_rss_date(iso_date)

                    mb = 0
                    imdb_id = None
                    password = ""

                    link = generate_download_link(
                        shared_state,
                        title,
                        thread_url,
                        mb,
                        password,
                        imdb_id or "",
                        self.initials,
                    )

                    releases.append(
                        {
                            "details": {
                                "title": title,
                                "hostname": self.initials,
                                "imdb_id": imdb_id,
                                "link": link,
                                "size": mb * 1024 * 1024,
                                "date": published,
                                "source": thread_url,
                            },
                            "type": "protected",
                        }
                    )

                except Exception as e:
                    debug(f"error parsing Forum item: {e}")
                    continue

        except Exception as e:
            warn(f"Forum feed error: {e}")
            mark_hostname_issue(
                self.initials, "feed", str(e) if "e" in dir() else "Error occurred"
            )
            invalidate_session(shared_state)

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases

    def _search_single_page(
        self,
        shared_state,
        host,
        search_string,
        search_id,
        page_num,
        imdb_id,
        search_category,
        season,
        episode,
    ):
        """
        Search a single page. This method is called sequentially for each page.
        """
        page_releases = []

        base_search_category = get_base_search_category_id(search_category)

        search_string = replace_umlauts(search_string)

        try:
            if page_num == 1:
                search_params = {"keywords": search_string, "c[title_only]": 1}
                search_url = f"https://www.{host}/search/search"
            else:
                if not search_id:
                    return page_releases, None

                search_params = {"page": page_num, "q": search_string, "o": "relevance"}
                search_url = f"https://www.{host}/search/{search_id}/"

            search_response = fetch_via_requests_session(
                shared_state,
                method="GET",
                target_url=search_url,
                get_params=search_params,
                timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
            )

            if search_response.status_code != 200:
                debug(
                    f"[Page {page_num}] returned status {search_response.status_code}"
                )
                return page_releases, None

            # Extract search ID from first page
            extracted_search_id = None
            if page_num == 1:
                match = re.search(r"/search/(\d+)/", search_response.url)
                if match:
                    extracted_search_id = match.group(1)
                    trace(f"[Page 1] Extracted search ID: {extracted_search_id}")

            soup = BeautifulSoup(search_response.text, "html.parser")
            result_items = soup.select("li.block-row")

            if not result_items:
                trace(f"[Page {page_num}] found 0 results")
                return page_releases, extracted_search_id

            trace(f"[Page {page_num}] found {len(result_items)} results")

            for item in result_items:
                try:
                    title_elem = item.select_one("h3.contentRow-title a")
                    if not title_elem:
                        continue

                    # Skip "Wird gesucht" threads
                    label = item.select_one(".contentRow-minor .label")
                    if label and "wird gesucht" in label.get_text(strip=True).lower():
                        continue

                    title = "".join(title_elem.strings)

                    title = re.sub(r"\s+", " ", title)
                    title = unescape(title)
                    title_normalized = _normalize_title_for_arr(title)

                    # Filter: Skip if no resolution or codec info (unless Magazarr/Lidarr)
                    if base_search_category not in [SEARCH_CAT_BOOKS, SEARCH_CAT_MUSIC]:
                        if not (
                            RESOLUTION_REGEX.search(title_normalized)
                            or CODEC_REGEX.search(title_normalized)
                        ):
                            continue

                    # Filter: Skip XXX content unless explicitly searched for
                    if (
                        XXX_REGEX.search(title_normalized)
                        and "xxx" not in search_string.lower()
                    ):
                        continue

                    thread_url = title_elem.get("href")
                    if thread_url.startswith("/"):
                        thread_url = f"https://www.{host}{thread_url}"

                    if not is_valid_release(
                        title_normalized,
                        search_category,
                        search_string,
                        season,
                        episode,
                    ):
                        continue

                    # Extract date and convert to RFC 2822 format
                    date_elem = item.select_one("time.u-dt")
                    iso_date = date_elem.get("datetime", "") if date_elem else ""
                    published = _convert_to_rss_date(iso_date)

                    mb = 0
                    password = ""

                    link = generate_download_link(
                        shared_state,
                        title_normalized,
                        thread_url,
                        mb,
                        password,
                        imdb_id or "",
                        self.initials,
                    )

                    page_releases.append(
                        {
                            "details": {
                                "title": title_normalized,
                                "hostname": self.initials,
                                "imdb_id": imdb_id,
                                "link": link,
                                "size": mb * 1024 * 1024,
                                "date": published,
                                "source": thread_url,
                            },
                            "type": "protected",
                        }
                    )

                    if _is_current_year_jahresthema_thread(
                        title, search_string, base_search_category
                    ):
                        page_releases.extend(
                            _expand_jahresthema_thread_releases(
                                shared_state,
                                host,
                                thread_url,
                                search_string,
                                imdb_id,
                                self.initials,
                                search_category,
                            )
                        )

                except Exception as e:
                    debug(f"[Page {page_num}] error parsing item: {e}")

            return page_releases, extracted_search_id

        except Exception as e:
            warn(f"[Page {page_num}] error: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            return page_releases, None

    def search(
        self,
        shared_state: shared_state,
        start_time: float,
        search_category: str,
        search_string: str = "",
        season: int = None,
        episode: int = None,
    ) -> list[SearchRelease]:
        """
        Search with sequential pagination to find best quality releases.
        Stops searching if a page returns 0 results or 10 seconds have elapsed.
        """
        releases = []
        host = shared_state.values["config"]("Hostnames").get(self.initials)

        imdb_id = is_imdb_id(search_string)
        if imdb_id:
            title = get_localized_title(shared_state, imdb_id, "de")
            if not title:
                info(f"no title for IMDb {imdb_id}")
                return releases
            search_string = title
            if not season:
                if year := get_year(imdb_id):
                    search_string += f" {year}"

        search_string = unescape(search_string)
        max_search_duration = 7

        trace(
            f"Starting sequential paginated search for '{search_string}' (Season: {season}, Episode: {episode}) - max {max_search_duration}s"
        )

        try:
            sess = retrieve_and_validate_session(shared_state)
            if not sess:
                warn(f"Could not retrieve valid session for {host}")
                return releases

            search_id = None
            page_num = 0
            search_start_time = time.time()
            release_titles_per_page = set()

            # Sequential search through pages until timeout or no results
            while (time.time() - search_start_time) < max_search_duration:
                page_num += 1

                page_releases, extracted_search_id = self._search_single_page(
                    shared_state,
                    host,
                    search_string,
                    search_id,
                    page_num,
                    imdb_id,
                    search_category,
                    season,
                    episode,
                )

                page_release_titles = tuple(
                    pr["details"]["title"] for pr in page_releases
                )
                if page_release_titles in release_titles_per_page:
                    trace(f"[Page {page_num}] duplicate page detected, stopping")
                    break
                release_titles_per_page.add(page_release_titles)

                # Update search_id from first page
                if page_num == 1:
                    search_id = extracted_search_id
                    if not search_id:
                        trace("Could not extract search ID, stopping pagination")
                        break

                # Add releases from this page
                releases.extend(page_releases)
                trace(
                    f"[Page {page_num}] completed with {len(page_releases)} valid releases"
                )

                # Stop if this page returned 0 results
                if len(page_releases) == 0:
                    trace(f"[Page {page_num}] returned 0 results, stopping pagination")
                    break

        except Exception as e:
            info(f"search error: {e}")
            mark_hostname_issue(
                self.initials, "search", str(e) if "e" in dir() else "Error occurred"
            )
            invalidate_session(shared_state)

        trace(
            f"FINAL - Found {len(releases)} valid releases - providing to {search_category}"
        )

        elapsed = time.time() - start_time
        debug(f"Time taken: {elapsed:.2f}s")

        if releases:
            clear_hostname_issue(self.initials)
        return releases


def _convert_to_rss_date(iso_date_str):
    """
    Convert ISO format datetime to RSS date format.
    DL date format: '2025-12-15T20:43:06+0100'
    Returns: 'Sun, 15 Dec 2025 20:43:06 +0100'
    Falls back to current time if conversion fails.
    """
    if not iso_date_str:
        return datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    try:
        dt_obj = datetime.fromisoformat(iso_date_str)
        return dt_obj.strftime("%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        return datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")


def _normalize_title_for_arr(title):
    """
    Normalize title for *arr by replacing spaces with dots.
    """
    title = title.replace(" ", ".")
    title = re.sub(r"\s*-\s*", "-", title)
    title = re.sub(r"\.\-\.", "-", title)
    title = re.sub(r"\.{2,}", ".", title)
    title = title.strip(".")
    return title


def _is_current_year_jahresthema_thread(title, search_string, base_search_category):
    if base_search_category != SEARCH_CAT_BOOKS:
        return False

    title_text = str(title or "")
    title_lower = title_text.lower()
    current_year = str(datetime.now().year)

    if "jahresthema" not in title_lower and "sammelthema" not in title_lower:
        return False
    if current_year not in title_text:
        return False

    return _magazine_title_matches(search_string, title_text)


def _magazine_title_matches(search_string, title):
    search_tokens = set(_magazine_match_tokens(search_string))
    title_tokens = set(_magazine_match_tokens(title))

    if not search_tokens or not title_tokens:
        return False

    return search_tokens.issubset(title_tokens)


def _magazine_match_tokens(text):
    text = replace_umlauts(unescape(str(text or ""))).lower()
    text = re.sub(r"\bc\s*['`´’]?\s*t\b", "ct", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)

    ignored = {
        "der",
        "die",
        "das",
        "the",
        "magazin",
        "magazine",
        "nachrichtenmagazin",
        "zeitschrift",
        "jahresthema",
        "sammelthema",
        "jahrgang",
    }

    tokens = []
    for token in text.split():
        if token in ignored:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", token):
            continue
        tokens.append(token)

    return tokens


def _expand_jahresthema_thread_releases(
    shared_state,
    host,
    thread_url,
    search_string,
    imdb_id,
    source_key,
    search_category,
):
    releases = []
    seen = set()

    try:
        first_page = _fetch_thread_page(shared_state, thread_url)
        if first_page is None:
            return releases

        last_page = _extract_last_thread_page(first_page.text)
        start_page = max(1, last_page - 4)

        page_responses = {}
        if start_page == 1:
            page_responses[1] = first_page

        for page_num in range(start_page, last_page + 1):
            response = page_responses.get(page_num)
            page_url = _thread_page_url(thread_url, page_num)
            if response is None:
                response = _fetch_thread_page(shared_state, page_url)
            if response is None:
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            for post in soup.select("article.message--post"):
                release = _release_from_jahresthema_post(
                    shared_state,
                    host,
                    post,
                    page_url,
                    search_string,
                    imdb_id,
                    source_key,
                    search_category,
                )
                if not release:
                    continue

                dedupe_key = release["details"]["title"].strip().casefold()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                releases.append(release)

    except Exception as e:
        debug(f"error expanding Jahresthema thread {thread_url}: {e}")

    if releases:
        trace(f"Expanded Jahresthema thread {thread_url} into {len(releases)} issues")
    return releases


def _fetch_thread_page(shared_state, page_url):
    response = fetch_via_requests_session(
        shared_state,
        method="GET",
        target_url=page_url,
        timeout=SEARCH_REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        debug(f"Jahresthema page returned status {response.status_code}: {page_url}")
        return None
    return response


def _extract_last_thread_page(html):
    soup = BeautifulSoup(html, "html.parser")
    page_numbers = [1]

    for element in soup.select("a.pageNav-page, .pageNav-main a, a.pageNav-jump"):
        text = element.get_text(" ", strip=True)
        if text.isdigit():
            page_numbers.append(int(text))

        href = element.get("href", "")
        match = re.search(r"(?:/page-|[?&]page=)(\d+)", href)
        if match:
            page_numbers.append(int(match.group(1)))

    return max(page_numbers)


def _thread_page_url(thread_url, page_num):
    split_url = urlsplit(thread_url)
    path = re.sub(r"/page-\d+/?$", "", split_url.path.rstrip("/"))
    if page_num > 1:
        path = f"{path}/page-{page_num}"

    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            path,
            split_url.query,
            "",
        )
    )


def _release_from_jahresthema_post(
    shared_state,
    host,
    post,
    page_url,
    search_string,
    imdb_id,
    source_key,
    search_category,
):
    if not _post_contains_supported_download(post):
        return None

    current_year = datetime.now().year
    issue_title = _extract_issue_title_from_post(post, search_string)
    if not issue_title:
        return None

    issue_title = _complete_issue_title(issue_title, search_string, current_year)
    title_normalized = _normalize_title_for_arr(issue_title)

    if not is_valid_release(title_normalized, search_category, search_string):
        return None

    post_url = _post_url(page_url, post)
    date_elem = post.select_one("time.u-dt")
    iso_date = date_elem.get("datetime", "") if date_elem else ""
    published = _convert_to_rss_date(iso_date)

    mb = 0
    password = ""
    link = generate_download_link(
        shared_state,
        title_normalized,
        post_url,
        mb,
        password,
        imdb_id or "",
        source_key,
    )

    return {
        "details": {
            "title": title_normalized,
            "hostname": source_key,
            "imdb_id": imdb_id,
            "link": link,
            "size": mb * 1024 * 1024,
            "date": published,
            "source": post_url,
        },
        "type": "protected",
    }


def _post_contains_supported_download(post):
    content = _own_message_content(post)
    for url in re.findall(r"https?://[^\s<>'\"]+", str(content), re.IGNORECASE):
        host = urlsplit(url).netloc.lower()

        direct_hoster = _normalize_direct_hoster_name(host)
        if direct_hoster in SHARE_HOSTERS_LOWERCASE:
            return True

        if re.search(r"(?:filecrypt|hide|keeplinks|tolink)\.", host, re.IGNORECASE):
            return True

    return False


def _normalize_direct_hoster_name(host):
    normalized = str(host or "").lower().strip()
    if "://" in normalized:
        parsed = urlsplit(normalized)
        normalized = parsed.netloc or parsed.path

    if normalized.startswith("www."):
        normalized = normalized[4:]

    normalized = normalized.split("/", 1)[0]
    normalized = normalized.split(":", 1)[0]
    normalized = normalized.split(".", 1)[0]

    if normalized == "rg":
        return "rapidgator"
    if normalized in {"ddl", "ddlto"}:
        return "ddownload"
    return normalized


def _extract_issue_title_from_post(post, search_string):
    content = _own_message_content(post)

    for selector in ("h1", "h2", "h3", "h4", "strong", "b"):
        for element in content.select(selector):
            candidate = _clean_issue_title(element.get_text(" ", strip=True))
            if _looks_like_issue_title(candidate, search_string):
                return candidate

    text = content.get_text("\n", strip=True)
    for line in text.splitlines():
        candidate = _clean_issue_title(line)
        if _looks_like_issue_title(candidate, search_string):
            return candidate

    return ""


def _own_message_content(post):
    content = post.select_one("div.bbWrapper") or post
    soup = BeautifulSoup(str(content), "html.parser")

    for element in soup.find_all("blockquote"):
        element.decompose()

    for element in soup.find_all(class_=True):
        classes = " ".join(str(class_name).lower() for class_name in element["class"])
        if "quote" in classes:
            element.decompose()

    return soup


def _clean_issue_title(title):
    title = unescape(str(title or ""))
    title = re.sub(r"https?://\S+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -:|")
    return title


def _looks_like_issue_title(title, search_string):
    if not title or len(title) < 3 or len(title) > 180:
        return False

    title_lower = title.lower()
    if title_lower in {
        "download",
        "mirror",
        "rapidgator",
        "ddownload",
        "turbobit",
        "nitroflare",
        "filecrypt",
        "keeplinks",
    }:
        return False
    if re.search(r"(?:filecrypt|hide|keeplinks|tolink)\.", title_lower):
        return False

    if re.search(
        r"\b(?:download|mirror|passwort|password|size|groesse|grosse|größe|mb|gb)\b",
        replace_umlauts(title_lower),
    ):
        return False

    normalized_title = replace_umlauts(title_lower)
    has_issue_marker = re.search(
        r"\b(?:nr|no|issue|ausgabe|heft)\.?\s*\d{1,3}(?:\s*/\s*\d{2,4})?\b",
        normalized_title,
        re.IGNORECASE,
    )
    has_year = re.search(r"\b(?:19|20)\d{2}\b", title)
    has_date_context = _has_issue_date_context(normalized_title)
    has_magazine = _magazine_title_matches(search_string, title)

    return bool(
        (has_magazine and (has_issue_marker or has_date_context))
        or (has_issue_marker and (has_year or has_date_context or has_magazine))
        or (has_date_context and (has_magazine or has_issue_marker))
    )


def _has_issue_date_context(normalized_title):
    month_pattern = (
        r"january|february|march|april|may|june|july|august|september|october|"
        r"november|december|januar|februar|maerz|marz|april|mai|juni|juli|"
        r"august|september|oktober|november|dezember"
    )
    if re.search(
        rf"\b(?:\d{{1,2}}\s+)?(?:{month_pattern})\s+(?:19|20)\d{{2}}\b",
        normalized_title,
    ):
        return True
    if re.search(
        rf"\b\d{{1,2}}\.\s*(?:{month_pattern})\s+(?:19|20)\d{{2}}\b",
        normalized_title,
    ):
        return True
    if re.search(r"\b\d{1,3}\s*/\s*(?:19|20)\d{2}\b", normalized_title):
        return True
    if re.search(r"\b\d{1,3}\s+(?:19|20)\d{2}\b", normalized_title):
        return True
    if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", normalized_title):
        return True

    return False


def _complete_issue_title(issue_title, search_string, current_year):
    completed = issue_title

    if not _magazine_title_matches(search_string, completed):
        completed = f"{search_string} {completed}"
    if not re.search(r"(?:19|20)\d{2}", completed):
        completed = f"{completed} {current_year}"

    return completed


def _post_url(page_url, post):
    fragment = _post_fragment(post)
    if not fragment:
        return page_url

    split_url = urlsplit(page_url)
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            split_url.query,
            fragment,
        )
    )


def _post_fragment(post):
    for attr in ("data-content", "id"):
        value = str(post.get(attr) or "").strip("#")
        if value:
            return value

    for link in post.select("a[href]"):
        fragment = urlsplit(link.get("href", "")).fragment
        if fragment:
            return fragment

    return ""
