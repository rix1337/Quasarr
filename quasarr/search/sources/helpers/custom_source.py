# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""User-defined sources built from a stored definition instead of a module."""

import re
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import NamedTuple
from urllib.parse import parse_qsl, quote_plus, urljoin, urlparse

import requests
import soupsieve
from bs4 import BeautifulSoup, UnicodeDammit

from quasarr.constants import (
    DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    FEED_REQUEST_TIMEOUT_SECONDS,
    IMDB_REGEX,
    MONTHS_MAP,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_XXX,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
    SHARE_HOSTERS_LOWERCASE,
)
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info, warn
from quasarr.providers.utils import sanitize_title
from quasarr.search.sources.helpers.search_source import AbstractSearchSource

CUSTOM_KEY_REGEX = re.compile(r"^[c-z][1-9]$")
BUNDLED_KEY_REGEX = re.compile(r"^[a-z]{2}$")
HOOK_POINTS = ("feed", "search", "download", "package_identity")
CAPABILITIES = (
    "supports_imdb",
    "supports_phrase",
    "supports_absolute_numbering",
    "supports_date_numbering",
    "requires_login",
    "requires_account",
    "invite_only",
    "requires_flaresolverr",
)
CUSTOM_CATEGORIES = (
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_XXX,
)
SEARCH_MODES = ("imdb", "title", "off")
SEARCH_METHODS = ("get", "post")
DOWNLOAD_FILTERS = ("known", "all")
PASSWORD_MODES = ("hostname", "none")
LIST_FIELDS = ("title", "link", "size", "date", "imdb")
REQUIRED_LIST_FIELDS = ("title", "link")
MAX_BODY_BYTES = 5 * 1024 * 1024
# ponytail: per-field text cap bounds parser work on hostile pages
MAX_FIELD_CHARS = 2000
MAX_TITLE_CHARS = 300
# a size above this is a parse error, not a release
MAX_SIZE_MB = 2 * 1024 * 1024
SKIP_SHARE_WARNING = 0.5
# every redirect costs requests inside the grab
MAX_REDIRECT_LINKS = 10
BLOCKED_ERROR = "Security check detected - configure FlareSolverr"
_LABEL_SEPARATORS = " \t\r\n:|-\u00a0"

_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
_RSS_LINK_OPEN = re.compile(r"<link>", re.I)
_RSS_LINK_CLOSE = re.compile(r"</link>", re.I)
# a size appended to a release name, as in "Name – 14.6 GB"
_TRAILING_SIZE = re.compile(r"[\s|/–—-]+[\d.,]+\s*[KMGT]i?B\s*$", re.I)
# a listing date shown before the release name, as in "05.11.2026 - 13:04 Name"
_LEADING_DATE = re.compile(
    r"^\s*\d{1,2}\.\d{1,2}\.\d{2,4}(?:\s*[-,]?\s*\d{1,2}:\d{2})?[\s|–—-]+"
)
_SIZE_REGEX = re.compile(r"(\d+(?:[.,]\d+)*)\s*([KMGT]i?B|B)\b", re.I)
_NUMBER_REGEX = re.compile(r"\d+(?:[.,]\d+)*")
_IMDB_ID_REGEX = re.compile(r"\b(tt\d{7,})\b")
_NUMERIC_DATE_REGEX = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?:\D+(\d{1,2}):(\d{2}))?"
)
_ISO_DATE_REGEX = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2}))?")
_NAMED_DATE_REGEX = re.compile(
    r"(\d{1,2})\.?\s+([^\W\d_]+)\.?\s+(\d{4})(?:\D+(\d{1,2}):(\d{2}))?"
)
_NAMED_DATE_US_REGEX = re.compile(
    r"([^\W\d_]+)\.?\s+(\d{1,2}),?\s+(\d{4})(?:\D+(\d{1,2}):(\d{2}))?"
)


class DefinitionError(ValueError):
    """A stored or submitted definition cannot be used."""


# --- Typed parsers -------------------------------------------------------


def _normalize_number(raw):
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        return float(raw.replace(thousands, "").replace(decimal, "."))
    return float(raw.replace(",", "."))


def parse_size(text, unit=None):
    """Return size in MB from text such as "1,4 GB"; None when no size is found."""
    text = (text or "")[:MAX_FIELD_CHARS]
    match = _SIZE_REGEX.search(text)
    if match:
        number, found_unit = match.groups()
    elif unit:
        number_match = _NUMBER_REGEX.search(text)
        if not number_match:
            return None
        number, found_unit = number_match.group(0), unit
    else:
        return None

    factors = {"B": 1 / 1024**2, "KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024**2}
    factor = factors.get(found_unit.upper().replace("I", ""))
    if factor is None:
        return None
    size_mb = int(_normalize_number(number) * factor)
    if size_mb <= 0 or size_mb > MAX_SIZE_MB:
        return None
    return size_mb


def _build_datetime(year, month, day, hour=None, minute=None):
    year = int(year)
    if year < 100:
        year += 2000
    return datetime(year, int(month), int(day), int(hour or 0), int(minute or 0))


def _month_number(name):
    return MONTHS_MAP.get(name.lower().rstrip("."))


def _parse_datetime(text, fmt=None):
    text = (text or "").strip()[:MAX_FIELD_CHARS]
    if not text:
        return None
    if fmt:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            return None
    for parser in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            return parser(text)
        except (TypeError, ValueError, IndexError):
            pass

    if match := _ISO_DATE_REGEX.search(text):
        year, month, day, hour, minute = match.groups()
        return _build_datetime(year, month, day, hour, minute)
    if match := _NUMERIC_DATE_REGEX.search(text):
        day, month, year, hour, minute = match.groups()
        return _build_datetime(year, month, day, hour, minute)
    if match := _NAMED_DATE_REGEX.search(text):
        day, month_name, year, hour, minute = match.groups()
        if month := _month_number(month_name):
            return _build_datetime(year, month, day, hour, minute)
    if match := _NAMED_DATE_US_REGEX.search(text):
        month_name, day, year, hour, minute = match.groups()
        if month := _month_number(month_name):
            return _build_datetime(year, month, day, hour, minute)
    return None


def parse_date(text, fmt=None, now=None):
    """Return an RFC 2822 date for text in common site formats; None if unknown."""
    try:
        parsed = _parse_datetime(text, fmt)
    except (OverflowError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if parsed > now + timedelta(days=1):
        parsed = now
    return format_datetime(parsed.astimezone(timezone.utc))


def parse_imdb_id(text):
    text = (text or "")[:MAX_FIELD_CHARS]
    match = IMDB_REGEX.search(text) or _IMDB_ID_REGEX.search(text)
    return match.group(1) if match else None


# --- Definition validation --------------------------------------------------


def _normalize_hostname(value):
    raw = str(value or "").strip().lower()
    if "://" not in raw:
        raw = f"https://{raw}"
    domain = urlparse(raw).hostname or ""
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain or "." not in domain.strip(".") or domain != domain.strip("."):
        raise DefinitionError("hostname: provide a full domain name")
    if any(part in SHARE_HOSTERS_LOWERCASE for part in domain.split(".")):
        raise DefinitionError("hostname: a file hoster cannot be a source")
    return domain


def _require_bool(value, name):
    if not isinstance(value, bool):
        raise DefinitionError(f"{name}: must be true or false")
    return value


def _require_choice(value, choices, name):
    if value not in choices:
        raise DefinitionError(f"{name}: must be one of {', '.join(choices)}")
    return value


def _require_template(value, name, needs_query=False):
    template = str(value or "").strip()
    if not (
        template.startswith("https://{host}") or template.startswith("http://{host}")
    ):
        raise DefinitionError(f"{name}: must start with https://{{host}}")
    rest = template.split("{host}", 1)[1]
    if rest and rest[0] not in "/?#":
        raise DefinitionError(f"{name}: a path must follow {{host}}")
    if needs_query and "{q}" not in template:
        raise DefinitionError(f"{name}: must contain {{q}}")
    return template


def _compile_selector(value, name, required):
    selector = str(value or "").strip()
    if not selector:
        if required:
            raise DefinitionError(f"{name}: selector is required")
        return None
    try:
        return soupsieve.compile(selector)
    except Exception as e:
        raise DefinitionError(f"{name}: invalid selector ({e})") from e


def _compile_field(spec, name, default_attr):
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise DefinitionError(f"{name}: must be an object")
    attr = str(spec.get("attr") or default_attr).strip()
    if not attr:
        raise DefinitionError(f"{name}: attribute is required")
    label = str(spec.get("label") or "").strip() or None
    if label and attr != "text":
        raise DefinitionError(f"{name}: a label only works with text")
    return {
        "selector": _compile_selector(spec.get("selector"), name, required=False),
        "attr": attr,
        "label": label,
        "format": str(spec.get("format") or "").strip() or None,
        "unit": str(spec.get("unit") or "").strip().upper() or None,
    }


def _compile_listing(spec, name):
    if not isinstance(spec, dict):
        raise DefinitionError(f"{name}: must be an object")
    listing = {"item": _compile_selector(spec.get("item"), f"{name}.item", True)}
    for field in LIST_FIELDS:
        default_attr = "href" if field == "link" else "text"
        listing[field] = _compile_field(
            spec.get(field), f"{name}.{field}", default_attr
        )
        if field in REQUIRED_LIST_FIELDS and listing[field] is None:
            raise DefinitionError(f"{name}.{field}: is required")
    size = listing["size"]
    if size and size["unit"] and size["unit"] not in ("B", "KB", "MB", "GB", "TB"):
        raise DefinitionError(f"{name}.size: unit must be B, KB, MB, GB or TB")
    return listing


def compile_definition(definition, bundled=False):
    """Validate a definition and return the parsed form CustomSource runs on.

    Bundled templates ship with Quasarr: they carry a two-letter key, take the
    hostname from the hostname settings and may link hooks, functions of their
    own module for what selectors cannot express. User definitions may not.
    """
    if not isinstance(definition, dict):
        raise DefinitionError("definition: must be an object")

    key = str(definition.get("key") or "").strip().lower()
    if bundled:
        if not BUNDLED_KEY_REGEX.match(key):
            raise DefinitionError("key: bundled templates use two letters")
    elif not CUSTOM_KEY_REGEX.match(key):
        raise DefinitionError("key: must be a letter from c to z and a digit")
    hooks = definition.get("hooks") or {}
    if hooks and not bundled:
        raise DefinitionError("hooks: only bundled templates may link code")
    if not isinstance(hooks, dict) or any(point not in HOOK_POINTS for point in hooks):
        raise DefinitionError(f"hooks: supported are {', '.join(HOOK_POINTS)}")
    capabilities = definition.get("capabilities") or {}
    if not isinstance(capabilities, dict) or any(
        name not in CAPABILITIES or not isinstance(value, bool)
        for name, value in capabilities.items()
    ):
        raise DefinitionError(f"capabilities: true/false for {', '.join(CAPABILITIES)}")
    declared_categories = definition.get("categories") or []
    if not isinstance(declared_categories, list) or any(
        c not in CUSTOM_CATEGORIES for c in declared_categories
    ):
        raise DefinitionError("categories: unsupported category")
    name = str(definition.get("name") or "").strip()
    if not name or len(name) > 60:
        raise DefinitionError("name: 1 to 60 characters")
    language = str(definition.get("language") or "").strip().lower()
    if not re.fullmatch(r"[a-z]{2}", language):
        raise DefinitionError("language: two-letter code such as de or en")

    feeds = definition.get("feeds") or []
    if not isinstance(feeds, list):
        raise DefinitionError("feeds: must be a list")
    compiled_feeds = {}
    for index, feed in enumerate(feeds):
        if not isinstance(feed, dict):
            raise DefinitionError(f"feeds[{index}]: must be an object")
        category = feed.get("category")
        if category not in CUSTOM_CATEGORIES:
            raise DefinitionError(f"feeds[{index}].category: unsupported category")
        if category in compiled_feeds:
            raise DefinitionError(f"feeds[{index}].category: listed twice")
        compiled_feeds[category] = _require_template(
            feed.get("url"), f"feeds[{index}].url"
        )

    search = definition.get("search") or {"mode": "off"}
    if not isinstance(search, dict):
        raise DefinitionError("search: must be an object")
    mode = _require_choice(search.get("mode", "off"), SEARCH_MODES, "search.mode")
    phrase = _require_bool(search.get("phrase", False), "search.phrase")
    search_categories = search.get("categories") or []
    if not isinstance(search_categories, list) or any(
        c not in CUSTOM_CATEGORIES for c in search_categories
    ):
        raise DefinitionError("search.categories: unsupported category")
    search_url = None
    search_method = _require_choice(
        search.get("method", "get"), SEARCH_METHODS, "search.method"
    )
    search_body = None
    if mode != "off" or phrase:
        # a POST form carries the query in its body instead of the URL
        is_post = search_method == "post"
        search_url = _require_template(search.get("url"), "search.url", not is_post)
        if is_post:
            search_body = str(search.get("body") or "").strip()
            if "{q}" not in search_body:
                raise DefinitionError("search.body: must contain {q}")
        if not search_categories:
            raise DefinitionError("search.categories: pick at least one")

    hooked = {"feed", "search"} & set(hooks)
    if not compiled_feeds and not search_url and not hooked:
        raise DefinitionError("feeds: add a feed or enable search")

    # a template whose feed and search are both hooks needs no selectors
    listing = (
        _compile_listing(definition.get("list"), "list")
        if definition.get("list") or hooked != {"feed", "search"}
        else None
    )
    search_listing = definition.get("search_list")
    search_listing = (
        _compile_listing(search_listing, "search_list") if search_listing else listing
    )

    # Without download links, releases must link to a crypter or hoster.
    download = definition.get("download") or {}
    if not isinstance(download, dict):
        raise DefinitionError("download: must be an object")
    links = download.get("links") or {}
    if not isinstance(links, dict):
        raise DefinitionError("download.links: must be an object")
    compiled_download = {
        "selector": _compile_selector(
            links.get("selector"), "download.links.selector", False
        ),
        "mirror": str(links.get("mirror") or "text").strip(),
        "filter": _require_choice(
            download.get("filter", "known"), DOWNLOAD_FILTERS, "download.filter"
        ),
        "password": _require_choice(
            download.get("password", "hostname"), PASSWORD_MODES, "download.password"
        ),
        # on-site links that redirect to a crypter or hoster
        "redirects": _require_bool(
            download.get("redirects", False), "download.redirects"
        ),
    }

    return {
        "key": key,
        "name": name,
        # bundled templates read the hostname settings on every use
        "hostname": None
        if bundled
        else _normalize_hostname(definition.get("hostname")),
        "bundled": bundled,
        "hooks": dict(hooks),
        "capabilities": dict(capabilities),
        "categories": declared_categories,
        "language": language,
        "flaresolverr": _require_bool(
            definition.get("flaresolverr", False), "flaresolverr"
        ),
        "feeds": compiled_feeds,
        "search_mode": mode,
        "phrase": phrase,
        "search_url": search_url,
        "search_method": search_method,
        "search_body": search_body,
        "search_categories": search_categories,
        "list": listing,
        "search_list": search_listing,
        "download": compiled_download,
    }


# --- Fetching --------------------------------------------------------------


def _is_on_host(url, hostname):
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    hostname = (hostname or "").lower().removeprefix("www.")
    return bool(hostname) and (host == hostname or host.endswith(f".{hostname}"))


class FetchResult(NamedTuple):
    markup: str | None
    error: str | None
    status: int | None
    # a security check answered the direct request
    blocked: bool = False


class _HostSession:
    """Cookies and User-Agent one host accepted, kept for this process."""

    def __init__(self):
        self.session = requests.Session()
        # the clearance cookie only counts together with the solver's browser
        self.user_agent = None


_host_sessions = {}
_host_sessions_lock = threading.Lock()


def _host_session(url):
    host = (urlparse(url).hostname or "").lower()
    with _host_sessions_lock:
        return _host_sessions.setdefault(host, _HostSession())


def _fetch_once(
    shared_state, url, timeout, via_flaresolverr, host_session=None, data=None
):
    from quasarr.providers.cloudflare import (
        flaresolverr_get,
        flaresolverr_post,
        is_cloudflare_challenge,
    )
    from quasarr.providers.utils import escape_unclosed_openers

    try:
        if via_flaresolverr and data is not None:
            response = flaresolverr_post(shared_state, url, data=data, timeout=timeout)
            status = response.status_code
            content = response.text.encode("utf-8")
        elif via_flaresolverr:
            response = flaresolverr_get(shared_state, url, timeout=timeout)
            status = response.status_code
            content = response.text.encode("utf-8")
        else:
            host_session = host_session or _host_session(url)
            headers = {
                "User-Agent": host_session.user_agent
                or shared_state.values["user_agent"]
            }
            method = "post" if data is not None else "get"
            with host_session.session.request(
                method, url, data=data, headers=headers, timeout=timeout, stream=True
            ) as response:
                status = response.status_code
                chunks = []
                size = 0
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > MAX_BODY_BYTES:
                        return FetchResult(None, "Page is larger than 5 MB", status)
                    chunks.append(chunk)
                content = b"".join(chunks)
    except Exception as e:
        return FetchResult(None, f"Request failed: {e}", None)

    if len(content) > MAX_BODY_BYTES:
        return FetchResult(None, "Page is larger than 5 MB", status)
    markup = escape_unclosed_openers(
        UnicodeDammit(content, is_html=True).unicode_markup or ""
    )
    if (
        not via_flaresolverr
        and not is_feed_markup(markup)
        and is_cloudflare_challenge(markup, include_passive_markers=False)
    ):
        return FetchResult(None, BLOCKED_ERROR, status, blocked=True)
    if status == 404:
        return FetchResult(None, "Page not found (404)", status)
    if not 200 <= status < 300:
        return FetchResult(None, f"HTTP status {status}", status)
    return FetchResult(markup, None, status)


def _refresh_clearance(shared_state, host_session, url, timeout):
    """Let FlareSolverr pass the check once and keep its cookies for the host."""
    from quasarr.providers.cloudflare import update_session_via_flaresolverr

    try:
        solved = update_session_via_flaresolverr(
            debug, shared_state, host_session.session, url, timeout=timeout
        )
    except Exception as e:
        debug(f"FlareSolverr could not pass the security check: {e}")
        return False
    if not solved or not solved.get("session"):
        return False
    host_session.user_agent = solved.get("user_agent") or host_session.user_agent
    return True


def fetch_markup(shared_state, url, timeout, use_flaresolverr, data=None):
    """Fetch a page and never raise.

    Every host keeps one session per process. A security check is passed once
    through FlareSolverr, whose cookies and User-Agent the session then reuses,
    so later pages load without the solver until the clearance expires. Only
    when the cookies do not satisfy the check does FlareSolverr fetch the page
    itself. This also applies to sites whose definition did not expect a check;
    ``use_flaresolverr`` documents that the site needs the solver.
    """
    from quasarr.providers.utils import is_flaresolverr_available

    host_session = _host_session(url)
    result = _fetch_once(shared_state, url, timeout, False, host_session, data)
    if not result.blocked:
        return result
    try:
        solver_ready = is_flaresolverr_available(shared_state)
    except Exception:
        solver_ready = False
    if not solver_ready:
        return result

    path = urlparse(url).path or "/"
    if _refresh_clearance(shared_state, host_session, url, timeout):
        retried = _fetch_once(shared_state, url, timeout, False, host_session, data)
        if not retried.blocked:
            debug(f"Security check on {path} passed, session cookies kept")
            return retried._replace(blocked=True)
    debug(f"Security check on {path}: loading the page through FlareSolverr")
    return _fetch_once(shared_state, url, timeout, True, data=data)._replace(
        blocked=True
    )


# --- Parsing ---------------------------------------------------------------


def _text_after_label(element, label):
    """Text after a label such as "Size:", in the same or the next text node."""
    wanted = label.casefold()
    strings = [str(node) for node in element.find_all(string=True)]
    for index, text in enumerate(strings):
        position = text.casefold().find(wanted)
        if position == -1:
            continue
        rest = text[position + len(label) :].strip(_LABEL_SEPARATORS)
        if rest:
            return rest
        for following in strings[index + 1 :]:
            value = following.strip(_LABEL_SEPARATORS)
            if value:
                return value
        return None
    return None


def extract_field(item, field):
    """Read one field from an item; None when the element or value is missing."""
    element = field["selector"].select_one(item) if field["selector"] else item
    if element is None:
        return None
    if field["attr"] == "text":
        if field["label"]:
            value = _text_after_label(element, field["label"])
        else:
            value = element.get_text(" ", strip=True)
    else:
        value = element.get(field["attr"])
        if isinstance(value, list):
            value = " ".join(value)
    value = str(value or "").strip()[:MAX_FIELD_CHARS]
    return value or None


def _resolve_link(page_url, href, hostname):
    if not href:
        return None
    link = urljoin(page_url, href)
    if urlparse(link).scheme not in ("http", "https"):
        return None
    # A release may link straight to its crypter or hoster: grabs then go
    # through the shared crypter detection instead of a release page.
    if not (_is_on_host(link, hostname) or _is_known_link(link)):
        return None
    return link


def _parse_item(item, page_url, listing, hostname, now):
    title = extract_field(item, listing["title"])
    if not title:
        return None, "title not found"
    title = sanitize_title(_LEADING_DATE.sub("", _TRAILING_SIZE.sub("", title)))
    if not title:
        return None, "title not found"
    if len(title) > MAX_TITLE_CHARS:
        return None, "title too long"

    href = extract_field(item, listing["link"])
    if not href:
        return None, "link not found"
    link = _resolve_link(page_url, href, hostname)
    if not link:
        return None, "link is not an http(s) link on this site"

    warnings = []
    size_mb = 0
    if listing["size"]:
        raw = extract_field(item, listing["size"])
        parsed = parse_size(raw, listing["size"]["unit"]) if raw else None
        if parsed is None:
            warnings.append("size not parsed")
        else:
            size_mb = parsed

    date = None
    if listing["date"]:
        raw = extract_field(item, listing["date"])
        date = parse_date(raw, listing["date"]["format"], now) if raw else None
        if date is None:
            warnings.append("date not parsed")

    imdb_id = None
    if listing["imdb"]:
        imdb_id = parse_imdb_id(extract_field(item, listing["imdb"]))
    else:
        for anchor in item.find_all("a", href=True):
            imdb_id = parse_imdb_id(anchor["href"])
            if imdb_id:
                break

    return {
        "title": title,
        "link": link,
        "size_mb": size_mb,
        "date": date or format_datetime(now),
        "imdb_id": imdb_id,
        "warnings": warnings,
    }, None


def is_feed_markup(markup):
    head = (markup or "")[:500].lstrip().lower()
    return head.startswith(("<?xml", "<rss", "<feed")) or "<rss" in head


def normalize_feed_markup(markup):
    """Keep RSS links readable: the HTML parser treats <link> as an empty tag."""
    if not is_feed_markup(markup):
        return markup
    # feeds are read with the HTML parser on purpose: lxml is not a dependency
    markup = _XML_DECLARATION.sub("", markup, count=1)
    # newer Python patch releases keep CDATA inside <title> as literal text,
    # so every CDATA section becomes plain escaped text up front
    from html import escape

    markup = re.sub(
        r"<!\[CDATA\[(.*?)\]\]>",
        lambda match: escape(match.group(1), quote=False),
        markup,
        flags=re.S,
    )
    return _RSS_LINK_OPEN.sub(
        "<permalink>", _RSS_LINK_CLOSE.sub("</permalink>", markup)
    )


def parse_listing(markup, page_url, listing, hostname, now=None):
    """Parse every item on its own so one broken item cannot hide the others."""
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(normalize_feed_markup(markup), "html.parser")
    items = listing["item"].select(soup)
    rows = []
    skipped = Counter()
    warnings = Counter()
    seen_links = set()

    for item in items:
        try:
            row, reason = _parse_item(item, page_url, listing, hostname, now)
        except Exception as e:
            row, reason = None, f"item failed: {type(e).__name__}"
        if row is None:
            skipped[reason] += 1
            continue
        if row["link"] in seen_links:
            skipped["duplicate link"] += 1
            continue
        seen_links.add(row["link"])
        warnings.update(row["warnings"])
        rows.append(row)

    return {
        "items": len(items),
        "rows": rows,
        "skipped": dict(skipped),
        "warnings": dict(warnings),
    }


def _is_known_link(url):
    from quasarr.downloads import detect_crypter

    if detect_crypter(url)[0]:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(part in SHARE_HOSTERS_LOWERCASE for part in host.split("."))


def parse_download_links(markup, page_url, download, hostname=None):
    """Return [[url, mirror]] for every link the definition selects."""
    soup = BeautifulSoup(markup, "html.parser")
    links = []
    seen = set()
    for element in download["selector"].select(soup):
        try:
            href = element.get("href")
            url = urljoin(page_url, href) if href else None
            if not url or urlparse(url).scheme not in ("http", "https"):
                continue
            if url in seen:
                continue
            if download["filter"] == "known" and not (
                _is_known_link(url)
                or (download["redirects"] and hostname and _is_on_host(url, hostname))
            ):
                continue
            mirror_mode = download["mirror"]
            if mirror_mode == "text":
                mirror = element.get_text(" ", strip=True)
                if mirror.startswith(("http://", "https://")):
                    mirror = (urlparse(mirror).hostname or "").removeprefix("www.")
            elif mirror_mode == "href_host":
                mirror = (urlparse(url).hostname or "").removeprefix("www.")
            else:
                mirror = element.get(mirror_mode) or ""
            seen.add(url)
            links.append([url, str(mirror).strip()[:100].lower()])
        except Exception as e:
            debug(f"Skipping download link: {e}")
    return links


def describe_report(report):
    """Return the hostname issue for a parse report, or None when it is usable."""
    if report["rows"]:
        return None
    if not report["items"]:
        return "Layout changed: no items matched the item selector"
    reason, count = max(report["skipped"].items(), key=lambda pair: pair[1])
    return f"All {report['items']} items were skipped: {reason} ({count})"


# --- Source ------------------------------------------------------------------


class CustomSource(AbstractSearchSource, AbstractDownloadSource):
    """One site serving both the search and download contracts.

    User definitions and bundled templates run through the same code. A
    bundled template may pass ``hooks``: functions that replace one step and are
    called with this source first, then the arguments of that step.
    """

    def __init__(self, definition, bundled=False, hooks=None):
        self.definition = definition
        self.spec = compile_definition(definition, bundled=bundled)
        self.hooks = hooks or {}
        missing = set(self.spec["hooks"]) - set(self.hooks)
        if missing:
            raise DefinitionError(f"hooks: {', '.join(sorted(missing))} not found")

    @property
    def hostname(self):
        if not self.spec["bundled"]:
            return self.spec["hostname"]
        from quasarr.providers import shared_state

        value = shared_state.values["config"]("Hostnames").get(self.initials)
        return str(value or "").strip().lower() or None

    def _capability(self, name, default):
        return self.spec["capabilities"].get(name, default)

    @property
    def initials(self):
        return self.spec["key"]

    @property
    def custom_hostname(self):
        # bundled templates keep their hostname in the hostname settings
        return None if self.spec["bundled"] else self.spec["hostname"]

    @property
    def name(self):
        return self.spec["name"]

    @property
    def language(self):
        return self.spec["language"]

    @property
    def supports_imdb(self):
        return self._capability("supports_imdb", self.spec["search_mode"] != "off")

    @property
    def supports_phrase(self):
        return self._capability("supports_phrase", self.spec["phrase"])

    @property
    def supports_absolute_numbering(self):
        return self._capability("supports_absolute_numbering", False)

    @property
    def supports_date_numbering(self):
        return self._capability("supports_date_numbering", False)

    @property
    def requires_login(self):
        return self._capability("requires_login", False)

    @property
    def requires_account(self):
        return self._capability("requires_account", False)

    @property
    def invite_only(self):
        return self._capability("invite_only", False)

    @property
    def requires_flaresolverr(self):
        return self._capability("requires_flaresolverr", self.spec["flaresolverr"])

    @property
    def supported_categories(self):
        categories = (
            set(self.spec["feeds"])
            | set(self.spec["search_categories"])
            | set(self.spec["categories"])
        )
        return sorted(categories)

    def _url(self, template, query=""):
        return template.replace("{host}", self.hostname).replace(
            "{q}", quote_plus(query)
        )

    def _password(self):
        return self.hostname if self.spec["download"]["password"] == "hostname" else ""

    def _releases(self, shared_state, rows):
        from quasarr.providers.utils import generate_download_link

        releases = []
        password = self._password()
        for row in rows:
            releases.append(
                {
                    "details": {
                        "title": row["title"],
                        "hostname": self.initials,
                        "imdb_id": row["imdb_id"],
                        "link": generate_download_link(
                            shared_state,
                            row["title"],
                            row["link"],
                            row["size_mb"],
                            password,
                            row["imdb_id"],
                            self.initials,
                        ),
                        "size": row["size_mb"] * 1024 * 1024,
                        "date": row["date"],
                        "source": row["link"],
                    },
                    "type": "protected",
                }
            )
        return releases

    def search_request(self, query):
        """URL and form data of one search; data is None for GET searches."""
        if self.spec["search_method"] != "post":
            return self._url(self.spec["search_url"], query), None
        body = self.spec["search_body"].replace("{q}", quote_plus(query))
        return self._url(self.spec["search_url"]), dict(parse_qsl(body))

    def load_listing(self, shared_state, url, listing, timeout, data=None):
        """Fetch and parse one listing page; returns (report, fetch result)."""
        fetched = fetch_markup(
            shared_state, url, timeout, self.spec["flaresolverr"], data
        )
        if fetched.error:
            return None, fetched
        report = parse_listing(fetched.markup, url, listing, self.hostname)
        return report, fetched

    def _log_report(self, operation, report):
        skipped = sum(report["skipped"].values())
        if not skipped:
            return
        message = f"{operation}: skipped {skipped} of {report['items']} items {report['skipped']}"
        if skipped > report["items"] * SKIP_SHARE_WARNING:
            warn(f"{self.initials.upper()} {message}")
        else:
            debug(f"{self.initials.upper()} {message}")

    def feed(self, shared_state, start_time, search_category):
        if "feed" in self.hooks:
            return self.hooks["feed"](self, shared_state, start_time, search_category)
        from quasarr.providers.utils import get_base_search_category_id

        try:
            category = get_base_search_category_id(search_category) or search_category
            template = self.spec["feeds"].get(int(category))
            if not template:
                return []
            report, fetched = self.load_listing(
                shared_state,
                self._url(template),
                self.spec["list"],
                FEED_REQUEST_TIMEOUT_SECONDS,
            )
            issue = fetched.error or describe_report(report)
            if issue:
                mark_hostname_issue(self.initials, "feed", issue)
                return []
            self._log_report("Feed", report)
            clear_hostname_issue(self.initials)
            return self._releases(shared_state, report["rows"])
        except Exception as e:
            mark_hostname_issue(self.initials, "feed", str(e))
            return []
        finally:
            debug(f"Time taken: {time.time() - start_time:.2f}s")

    def _search_query(self, shared_state, start_time, search_category, search_string):
        from quasarr.providers.imdb_metadata import get_localized_title
        from quasarr.providers.utils import is_imdb_id

        imdb_id = is_imdb_id(search_string)
        if not imdb_id:
            return search_string if self.spec["phrase"] else None, None
        if self.spec["search_mode"] == "imdb":
            return imdb_id, imdb_id
        if self.spec["search_mode"] == "title":
            title = get_localized_title(
                shared_state,
                imdb_id,
                self.spec["language"],
                search_category,
                deadline=start_time + SEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            return title, imdb_id
        return None, imdb_id

    def search(
        self,
        shared_state,
        start_time,
        search_category,
        search_string="",
        season=None,
        episode=None,
        **kwargs,
    ):
        if "search" in self.hooks:
            return self.hooks["search"](
                self,
                shared_state,
                start_time,
                search_category,
                search_string,
                season,
                episode,
                **kwargs,
            )
        from quasarr.providers.utils import (
            get_base_search_category_id,
            is_valid_release,
        )

        try:
            category = get_base_search_category_id(search_category) or search_category
            if int(category) not in self.spec["search_categories"]:
                return []
            query, imdb_id = self._search_query(
                shared_state, start_time, search_category, search_string
            )
            if not query:
                return []
            url, data = self.search_request(query)
            report, fetched = self.load_listing(
                shared_state,
                url,
                self.spec["search_list"],
                SEARCH_REQUEST_TIMEOUT_SECONDS,
                data,
            )
            if fetched.error:
                mark_hostname_issue(self.initials, "search", fetched.error)
                return []
            self._log_report("Search", report)
            clear_hostname_issue(self.initials)

            rows = []
            for row in report["rows"]:
                if imdb_id and row["imdb_id"] and row["imdb_id"] != imdb_id:
                    continue
                if not is_valid_release(
                    row["title"], search_category, search_string, season, episode
                ):
                    continue
                if imdb_id and not row["imdb_id"]:
                    row = {**row, "imdb_id": imdb_id}
                rows.append(row)
            return self._releases(shared_state, rows)
        except Exception as e:
            mark_hostname_issue(self.initials, "search", str(e))
            return []
        finally:
            debug(f"Time taken: {time.time() - start_time:.2f}s")

    def load_download_links(self, shared_state, url):
        """Fetch one release page; returns (links, error, status)."""
        if not _is_on_host(url, self.hostname):
            return [], "Release page is not on this site", None
        if not self.spec["download"]["selector"]:
            return [], "No download links configured", None
        fetched = fetch_markup(
            shared_state,
            url,
            DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            self.spec["flaresolverr"],
        )
        if fetched.error:
            return [], fetched.error, fetched.status
        links = parse_download_links(
            fetched.markup, url, self.spec["download"], self.hostname
        )
        if self.spec["download"]["redirects"]:
            links = self._resolve_redirects(shared_state, links)
        return links, None if links else "No download links matched", fetched.status

    def _resolve_redirects(self, shared_state, links):
        from quasarr.downloads.sources.helpers.redirect import (
            resolve_crypter_redirect,
        )
        from quasarr.providers.cloudflare import LazyFlareSolverrSession

        session = LazyFlareSolverrSession(shared_state)
        resolved = []
        try:
            for url, mirror in links:
                if not _is_on_host(url, self.hostname):
                    resolved.append([url, mirror])
                    continue
                if len(resolved) >= MAX_REDIRECT_LINKS:
                    break
                target = resolve_crypter_redirect(
                    url,
                    shared_state.values["user_agent"],
                    session,
                    self.initials,
                    host=self.hostname,
                    accept_offsite=True,
                )
                if target and _is_known_link(target):
                    resolved.append([target, mirror])
        finally:
            session.close()
        return resolved

    def get_download_links(self, shared_state, url, mirrors, title, password):
        if "download" in self.hooks:
            return self.hooks["download"](
                self, shared_state, url, mirrors, title, password
            )
        try:
            links, link_error, status = self.load_download_links(shared_state, url)
            if status == 404:
                # a removed release, not a broken site
                info(f"Release page for {title} no longer exists")
                return {"links": []}
            if link_error:
                if status is not None or "Request failed" in link_error:
                    mark_hostname_issue(self.initials, "download", link_error)
                return {"links": []}
            clear_hostname_issue(self.initials)
            return {"links": links}
        except Exception as e:
            mark_hostname_issue(self.initials, "download", str(e))
            return {"links": []}

    def get_package_identity(self, url):
        if "package_identity" in self.hooks:
            return self.hooks["package_identity"](self, url)
        return None
