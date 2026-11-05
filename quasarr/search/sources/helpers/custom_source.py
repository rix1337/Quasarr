# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""User-defined sources built from a stored definition instead of a module."""

import html
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
    SEARCH_CATEGORY_DEFINITIONS,
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
ALL_CATEGORIES = {
    definition["id"] for definition in SEARCH_CATEGORY_DEFINITIONS.values()
}
SEARCH_MODES = ("imdb", "title", "off")
SEARCH_MATCHES = ("imdb", "query")
IMDB_IDENTITIES = ("strict", "strict_fill", "fill", "none")
# exact compares bare hoster names, as "rapidgator" against "RG"
MIRROR_FILTERS = ("none", "mirror", "url", "exact")
# scene also drops listing dates and sizes around the name, sanitize does not
TITLE_CLEANUPS = ("scene", "sanitize", "none")
DATE_FALLBACKS = ("now", "hour_ago")
# release checks a search applies on top of the shared title matching
SEARCH_FILTERS = ("require_quality", "no_spaces", "skip_xxx")
SEARCH_METHODS = ("get", "post")
DOWNLOAD_FILTERS = ("known", "all")
PASSWORD_MODES = ("hostname", "site_name", "none")
LIST_FIELDS = ("title", "link", "size", "date", "imdb", "source", "password")
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
# every followed result page costs a request inside the search budget
MAX_FOLLOWED_PAGES = 5
BLOCKED_ERROR = "Security check detected - configure FlareSolverr"
_LABEL_SEPARATORS = " \t\r\n:|-\u00a0"

_TEXT_URL = re.compile(r"https?://[^\s<>'\"]+")
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
_UNIT_ONLY = re.compile(r"[KMGT]i?B", re.I)
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
    elif _UNIT_ONLY.fullmatch(text.strip()):
        # a unit without its number: the site does not know the size
        return 0
    else:
        return None

    factors = {"B": 1 / 1024**2, "KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024**2}
    factor = factors.get(found_unit.upper().replace("I", ""))
    if factor is None:
        return None
    size_mb = int(_normalize_number(number) * factor)
    # files below one MB report 0, as they always have
    if size_mb < 0 or size_mb > MAX_SIZE_MB:
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


def _string_list(value, name):
    value = value or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise DefinitionError(f"{name}: must be a list of texts")
    return value


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
    if isinstance(spec, list):
        # several ways to read one value: the first that finds it wins
        if not spec:
            raise DefinitionError(f"{name}: needs at least one way to read it")
        compiled = [
            _compile_field(s, f"{name}[{i}]", default_attr) for i, s in enumerate(spec)
        ]
        return {**compiled[0], "fallbacks": compiled[1:]}
    if not isinstance(spec, dict):
        raise DefinitionError(f"{name}: must be an object")
    attr = str(spec.get("attr") or default_attr).strip()
    if not attr:
        raise DefinitionError(f"{name}: attribute is required")
    raw_labels = spec.get("label") or []
    raw_labels = [raw_labels] if isinstance(raw_labels, str) else raw_labels
    if not isinstance(raw_labels, list):
        raise DefinitionError(f"{name}: label must be text or a list of texts")
    # several labels: the first that occurs in the item wins
    labels = [str(label).strip() for label in raw_labels if str(label).strip()]
    if labels and attr != "text":
        raise DefinitionError(f"{name}: a label only works with text")
    return {
        "selector": _compile_selector(spec.get("selector"), name, required=False),
        "attr": attr,
        "labels": labels,
        "format": str(spec.get("format") or "").strip() or None,
        "unit": str(spec.get("unit") or "").strip().upper() or None,
        # skip the release instead of falling back when the value is missing
        "required": _require_bool(spec.get("required", False), f"{name}.required"),
        # read from the closest enclosing element, as in a post holding releases
        "within": _compile_selector(spec.get("within"), f"{name}.within", False),
        "adjacent": _require_bool(spec.get("adjacent", False), f"{name}.adjacent"),
        "pick": _require_choice(
            spec.get("pick", "first"), ("first", "last"), f"{name}.pick"
        ),
        "fallbacks": [],
    }


def _compile_listing(spec, name):
    if not isinstance(spec, dict):
        raise DefinitionError(f"{name}: must be an object")
    listing = {"item": _compile_selector(spec.get("item"), f"{name}.item", True)}
    for field in LIST_FIELDS:
        default_attr = "href" if field in ("link", "source") else "text"
        listing[field] = _compile_field(
            spec.get(field), f"{name}.{field}", default_attr
        )
        if field in REQUIRED_LIST_FIELDS and listing[field] is None:
            raise DefinitionError(f"{name}.{field}: is required")
    size = listing["size"]
    if size and size["unit"] and size["unit"] not in ("B", "KB", "MB", "GB", "TB"):
        raise DefinitionError(f"{name}.size: unit must be B, KB, MB, GB or TB")
    # "scene" turns names into dotted release names, "none" keeps the page text
    listing["title_cleanup"] = _require_choice(
        spec.get("title_cleanup", "scene"), TITLE_CLEANUPS, f"{name}.title_cleanup"
    )
    listing["dedupe"] = _require_bool(spec.get("dedupe", True), f"{name}.dedupe")
    # releases point back to the page they were found on
    listing["source_is_page"] = _require_bool(
        spec.get("source_is_page", False), f"{name}.source_is_page"
    )
    # look for IMDb links in items without an imdb field
    listing["find_imdb"] = _require_bool(
        spec.get("find_imdb", True), f"{name}.find_imdb"
    )
    listing["date_fallback"] = _require_choice(
        spec.get("date_fallback", "now"), DATE_FALLBACKS, f"{name}.date_fallback"
    )
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
        c not in ALL_CATEGORIES for c in declared_categories
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
    feed_bodies = {}
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
        # a feed can be a form submitted without search terms
        method = _require_choice(
            feed.get("method", "get"), SEARCH_METHODS, f"feeds[{index}].method"
        )
        if method == "post":
            feed_bodies[category] = str(feed.get("body") or "")

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
    if (mode != "off" or phrase) and not search.get("urls"):
        # a POST form carries the query in its body instead of the URL
        is_post = search_method == "post"
        search_url = _require_template(search.get("url"), "search.url", not is_post)
        if is_post:
            search_body = str(search.get("body") or "").strip()
            if "{q}" not in search_body:
                raise DefinitionError("search.body: must contain {q}")
        if not search_categories:
            raise DefinitionError("search.categories: pick at least one")
    search_filters = search.get("filters") or []
    if not isinstance(search_filters, list) or any(
        f not in SEARCH_FILTERS for f in search_filters
    ):
        raise DefinitionError(
            f"search.filters: supported are {', '.join(SEARCH_FILTERS)}"
        )
    # strict drops results of another title and fills in the searched IMDb ID,
    # fill always stamps the searched ID, none keeps what the page shows
    identity = search.get("imdb_identity", "strict")
    identity = {True: "strict", False: "none"}.get(identity, identity)
    imdb_identity = _require_choice(identity, IMDB_IDENTITIES, "search.imdb_identity")
    # imdb matches results against the searched ID, query against the title
    search_match = _require_choice(
        search.get("match", "imdb"), SEARCH_MATCHES, "search.match"
    )
    # the title query also names the release year, unless a season is searched
    append_year = _require_bool(search.get("append_year", False), "search.append_year")
    # the title query also names the season and episode, as in "Title S01E02"
    episode_query = _require_bool(
        search.get("episode_query", False), "search.episode_query"
    )
    # result pages that hold the releases, opened from the search page
    follow = search.get("follow") or None
    if follow is not None:
        if not isinstance(follow, dict) or not follow.get("selector"):
            raise DefinitionError("search.follow: a selector is required")
        limit = follow.get("limit", 1)
        if not isinstance(limit, int) or not 1 <= limit <= MAX_FOLLOWED_PAGES:
            raise DefinitionError(
                f"search.follow.limit: 1 to {MAX_FOLLOWED_PAGES} pages"
            )
        follow = {
            "selector": _compile_selector(follow["selector"], "search.follow", True),
            "limit": limit,
        }
    # a category can search several sections of the site at once
    raw_urls = search.get("urls") or {}
    if not isinstance(raw_urls, dict):
        raise DefinitionError("search.urls: must map categories to URLs")
    search_urls = {}
    for category, templates in raw_urls.items():
        if str(category) not in {str(c) for c in CUSTOM_CATEGORIES} or not isinstance(
            templates, list
        ):
            raise DefinitionError("search.urls: unsupported category")
        search_urls[int(category)] = [
            _require_template(t, f"search.urls[{category}]", True) for t in templates
        ]

    hooked = {"feed", "search"} & set(hooks)
    if search.get("urls") and not search_categories:
        raise DefinitionError("search.categories: pick at least one")
    if not compiled_feeds and not search_url and not search.get("urls") and not hooked:
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
    section = download.get("section") or None
    if section is not None and not (
        isinstance(section, dict) and section.get("heading") and section.get("contains")
    ):
        raise DefinitionError("download.section: heading and contains are required")
    hosts = download.get("hosts") or []
    if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
        raise DefinitionError("download.hosts: must be a list of hoster names")
    mirror_filter = download.get("filter_mirrors", "none")
    mirror_filter = {True: "mirror", False: "none"}.get(mirror_filter, mirror_filter)
    compiled_download = {
        "selector": _compile_selector(
            links.get("selector"), "download.links.selector", False
        ),
        # the release text lives in this element; missing means a changed layout
        "container": _compile_selector(
            download.get("container"), "download.container", False
        ),
        # only links between this heading and the next one of the same kind
        "section": section,
        # hoster names a link host must start with, as in "ddownload."
        "hosts": [h.lower().strip(".") for h in hosts],
        # mirror names a link must carry, as "rapidgator"
        "mirror_names": [
            normalize_hoster_name(n)
            for n in _string_list(download.get("mirror_names"), "download.mirror_names")
        ],
        # crypter keeps only redirects that end at a crypter
        "redirect_targets": _require_choice(
            download.get("redirect_targets", "any"),
            ("any", "crypter"),
            "download.redirect_targets",
        ),
        # URLs written as text, when no link qualifies
        "text_urls": _require_bool(
            download.get("text_urls", False), "download.text_urls"
        ),
        # read the IMDb ID from the release page
        "imdb": _require_bool(download.get("imdb", False), "download.imdb"),
        # a page without matching links marks the site as broken
        "empty_is_issue": _require_bool(
            download.get("empty_is_issue", True), "download.empty_is_issue"
        ),
        "mirror": str(links.get("mirror") or "text").strip(),
        "filter": _require_choice(
            download.get("filter", "known"), DOWNLOAD_FILTERS, "download.filter"
        ),
        "password": _require_choice(
            download.get("password", "hostname"), PASSWORD_MODES, "download.password"
        ),
        # mirror keeps links whose mirror name holds a wanted mirror, url
        # those whose address does
        "filter_mirrors": _require_choice(
            mirror_filter, MIRROR_FILTERS, "download.filter_mirrors"
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
        "search_filters": search_filters,
        "imdb_identity": imdb_identity,
        "search_match": search_match,
        "search_follow": follow,
        "search_append_year": append_year,
        "search_episode_query": episode_query,
        "feed_bodies": feed_bodies,
        # feed releases pass the same checks as search results without a query
        "feed_validate": _require_bool(
            definition.get("feed_validate", False), "feed_validate"
        ),
        "search_urls": search_urls,
        # Magazarr reads magazine dates only in a few spellings
        "magazine_titles": _require_bool(
            definition.get("magazine_titles", False), "magazine_titles"
        ),
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


def _text_after_label(element, label, adjacent=False):
    """Text after a label such as "Size:", in the same or a following text node.

    ``adjacent`` reads only the text node right after the label, so an empty
    value stays empty instead of picking up the next text on the page.
    """
    wanted = label.casefold()
    strings = [str(node) for node in element.find_all(string=True)]
    for index, text in enumerate(strings):
        position = text.casefold().find(wanted)
        if position == -1:
            continue
        rest = text[position + len(label) :].strip(_LABEL_SEPARATORS)
        if rest:
            return rest
        for following in strings[index + 1 : index + 2 if adjacent else None]:
            value = following.strip(_LABEL_SEPARATORS)
            if value:
                return value
        return None
    return None


def extract_field(item, field):
    """Read one field from an item; None when the element or value is missing."""
    value = _extract_one(item, field)
    for fallback in field.get("fallbacks") or []:
        if value:
            break
        value = _extract_one(item, fallback)
    return value


def _extract_one(item, field):
    base = item
    if field.get("within"):
        base = field["within"].closest(item)
        if base is None:
            return None
    if not field["selector"]:
        element = base
    elif field.get("pick") == "last":
        matches = field["selector"].select(base)
        element = matches[-1] if matches else None
    else:
        element = field["selector"].select_one(base)
    if element is None:
        return None
    if field["attr"] == "text":
        if field["labels"]:
            value = next(
                (
                    found
                    for label in field["labels"]
                    if (
                        found := _text_after_label(
                            element, label, field.get("adjacent")
                        )
                    )
                ),
                None,
            )
        else:
            value = element.get_text(" ", strip=True)
    elif field["attr"] == "html":
        # the element's markup, for values hidden in attributes or comments
        value = str(element)
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


def _typed_value(item, field, parse):
    """The first of a field's ways to read it whose value also parses."""
    for way in [field, *(field.get("fallbacks") or [])]:
        raw = _extract_one(item, way)
        value = parse(raw, way) if raw else None
        if value is not None:
            return value
    return None


def _parse_item(item, page_url, listing, hostname, now):
    title = extract_field(item, listing["title"])
    if not title:
        return None, "title not found"
    if listing["title_cleanup"] == "scene":
        title = sanitize_title(_LEADING_DATE.sub("", _TRAILING_SIZE.sub("", title)))
    elif listing["title_cleanup"] == "sanitize":
        title = sanitize_title(title)
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
        parsed = _typed_value(
            item, listing["size"], lambda raw, f: parse_size(raw, f["unit"])
        )
        if parsed is None:
            if listing["size"]["required"]:
                return None, "size not found"
            warnings.append("size not parsed")
        else:
            size_mb = parsed

    date = None
    if listing["date"]:
        date = _typed_value(
            item, listing["date"], lambda raw, f: parse_date(raw, f["format"], now)
        )
        if date is None:
            if listing["date"]["required"]:
                return None, "date not found"
            warnings.append("date not parsed")

    imdb_id = None
    if listing["imdb"]:
        imdb_id = _typed_value(item, listing["imdb"], lambda raw, f: parse_imdb_id(raw))
    elif listing["find_imdb"]:
        for anchor in item.find_all("a", href=True):
            imdb_id = parse_imdb_id(anchor["href"])
            if imdb_id:
                break
        if not imdb_id:
            match = IMDB_REGEX.search(item.get_text()[: MAX_FIELD_CHARS * 10])
            imdb_id = match.group(1) if match else None

    # a release-specific archive password: the first word after its label
    password = None
    if listing["password"]:
        raw = extract_field(item, listing["password"])
        password = raw.split()[0] if raw else ""

    # the page a release is shown on, when its link is a crypter or hoster
    source = page_url if listing["source_is_page"] else link
    if listing["source"]:
        source = (
            _resolve_link(page_url, extract_field(item, listing["source"]), hostname)
            or link
        )
    return {
        "title": title,
        "link": link,
        "source": source,
        "password": password,
        "size_mb": size_mb,
        "date": date
        or format_datetime(
            now - timedelta(hours=1) if listing["date_fallback"] == "hour_ago" else now
        ),
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
        if listing["dedupe"] and row["link"] in seen_links:
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


def _download_anchors(soup, download):
    """Links in the download area: a heading's section, else the container."""
    root = soup
    if download["container"]:
        root = download["container"].select_one(soup)
        if root is None:
            return None
    section = download["section"]
    if section:
        heading = root.find(
            lambda t: (
                t.name == section["heading"]
                and section["contains"].lower() in t.get_text(strip=True).lower()
            )
        )
        if heading is not None:
            anchors = []
            for sibling in heading.next_siblings:
                if getattr(sibling, "name", None) == section["heading"]:
                    break
                if hasattr(sibling, "find_all"):
                    anchors += sibling.find_all("a", href=True)
            return anchors
    if download["selector"]:
        return download["selector"].select(root)
    return root.find_all("a", href=True)


_HOSTER_ALIASES = {"ddl": "ddownload", "ddlto": "ddownload", "rg": "rapidgator"}


def normalize_hoster_name(name):
    """A bare hoster name from a label, a domain or a URL: "RG" -> "rapidgator"."""
    normalized = str(name or "").lower().strip()
    if "://" in normalized:
        parsed = urlparse(normalized)
        normalized = parsed.netloc or parsed.path
    normalized = normalized.removeprefix("www.").split("/", 1)[0].split(":", 1)[0]
    if " " in normalized:
        normalized = normalized.split()[-1]
    normalized = normalized.split(".", 1)[0]
    return _HOSTER_ALIASES.get(normalized, normalized)


def _host_allowed(url, download):
    host = (urlparse(url).hostname or "").lower()
    if download["hosts"]:
        return any(host.startswith(f"{name}.") for name in download["hosts"])
    return True


def _mirror_name(element, url, mode):
    host = (urlparse(url).hostname or "").lower()
    if mode == "text":
        mirror = element.get_text(" ", strip=True) if element is not None else ""
        if mirror.startswith(("http://", "https://")):
            mirror = (urlparse(mirror).hostname or "").removeprefix("www.")
    elif mode == "href_host":
        mirror = host.removeprefix("www.")
    elif mode == "host_label":
        mirror = host.split(".")[0] if host else "unknown"
    elif mode == "hoster_name":
        text = element.get_text(" ", strip=True) if element is not None else ""
        mirror = normalize_hoster_name(text or host)
    else:
        mirror = (element.get(mode) if element is not None else "") or ""
    return str(mirror).strip()[:100].lower()


def parse_download_links(markup, page_url, download, hostname=None):
    """Return [[url, mirror]] for every link the definition selects.

    Returns None when the configured container is missing from the page.
    """
    soup = BeautifulSoup(markup, "html.parser")
    anchors = _download_anchors(soup, download)
    if anchors is None:
        return None
    links = []
    seen = set()

    def accept(url, element):
        if not url or urlparse(url).scheme not in ("http", "https") or url in seen:
            return
        mirror = _mirror_name(element, url, download["mirror"])
        if download["mirror_names"] and mirror not in download["mirror_names"]:
            return
        if download["hosts"]:
            if not _host_allowed(url, download):
                return
        elif download["filter"] == "known" and not (
            _is_known_link(url)
            or (download["redirects"] and hostname and _is_on_host(url, hostname))
        ):
            return
        seen.add(url)
        links.append([url, mirror])

    for element in anchors:
        try:
            href = (element.get("href") or "").strip()
            accept(urljoin(page_url, href) if href else None, element)
        except Exception as e:
            debug(f"Skipping download link: {e}")
    if not links and download["text_urls"]:
        text = "".join(str(anchor) for anchor in anchors)
        for url in _TEXT_URL.findall(text):
            accept(url.strip(), None)
    return links


def page_imdb_id(markup):
    """The first IMDb title link of a release page."""
    match = IMDB_REGEX.search(
        " ".join(
            a["href"]
            for a in BeautifulSoup(markup, "html.parser").find_all("a", href=True)
        )
    )
    return match.group(1) if match else None


def passes_search_filters(title, filters, search_string=""):
    """Release checks a template adds to the shared title matching."""
    from quasarr.constants import CODEC_REGEX, RESOLUTION_REGEX, XXX_REGEX

    if "skip_xxx" in filters and XXX_REGEX.search(title):
        if "xxx" not in (search_string or "").lower():
            return False
    if "require_quality" in filters and not (
        RESOLUTION_REGEX.search(title) or CODEC_REGEX.search(title)
    ):
        return False
    if "no_spaces" in filters and " " in title:
        return False
    return True


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
        mode = self.spec["download"]["password"]
        if mode == "hostname":
            return self.hostname
        if mode == "site_name":
            return (self.hostname or "").split(".")[0]
        return ""

    def _releases(self, shared_state, rows):
        from quasarr.providers.utils import generate_download_link

        releases = []
        site_password = self._password()
        for row in rows:
            password = site_password if row.get("password") is None else row["password"]
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
                        "source": row.get("source") or row["link"],
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
        return self._url(self.spec["search_url"]), dict(
            parse_qsl(body, keep_blank_values=True)
        )

    def feed_request(self, category):
        """URL and form data of the feed of one category."""
        template = self.spec["feeds"].get(int(category))
        if not template:
            return None, None
        body = self.spec["feed_bodies"].get(int(category))
        data = None if body is None else dict(parse_qsl(body, keep_blank_values=True))
        return self._url(template), data

    def search_requests(self, query, category):
        """Every request of one search: per-category sections, else the default."""
        templates = self.spec["search_urls"].get(int(category))
        if templates:
            return [(self._url(t, query), None) for t in templates]
        return [self.search_request(query)]

    def _followed_pages(self, shared_state, requests_):
        """Result pages linked from the search pages, as GET requests."""
        follow = self.spec["search_follow"]
        pages = []
        for url, data in requests_:
            fetched = fetch_markup(
                shared_state,
                url,
                SEARCH_REQUEST_TIMEOUT_SECONDS,
                self.spec["flaresolverr"],
                data,
            )
            if fetched.error:
                mark_hostname_issue(self.initials, "search", fetched.error)
                continue
            soup = BeautifulSoup(fetched.markup, "html.parser")
            for anchor in follow["selector"].select(soup):
                target = urljoin(url, anchor.get("href") or "")
                if _is_on_host(target, self.hostname) and (target, None) not in pages:
                    pages.append((target, None))
                if len(pages) >= follow["limit"]:
                    return pages
        return pages

    def _magazine(self, title, category):
        from quasarr.constants import SEARCH_CAT_BOOKS
        from quasarr.providers.utils import normalize_magazine_title

        if self.spec["magazine_titles"] and int(category) == SEARCH_CAT_BOOKS:
            return normalize_magazine_title(title)
        return title

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
        from quasarr.providers.utils import (
            get_base_search_category_id,
            is_valid_release,
        )

        try:
            category = get_base_search_category_id(search_category) or search_category
            url, data = self.feed_request(category)
            if not url:
                return []
            report, fetched = self.load_listing(
                shared_state, url, self.spec["list"], FEED_REQUEST_TIMEOUT_SECONDS, data
            )
            issue = fetched.error or describe_report(report)
            if issue:
                mark_hostname_issue(self.initials, "feed", issue)
                return []
            self._log_report("Feed", report)
            clear_hostname_issue(self.initials)
            rows = [
                {**row, "title": self._magazine(row["title"], category)}
                for row in report["rows"]
                if not self.spec["feed_validate"]
                or is_valid_release(row["title"], search_category, "", None, None)
            ]
            return self._releases(shared_state, rows)
        except Exception as e:
            mark_hostname_issue(self.initials, "feed", str(e))
            return []
        finally:
            debug(f"Time taken: {time.time() - start_time:.2f}s")

    def _search_query(
        self, shared_state, start_time, search_category, search_string, season=None
    ):
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
            if title and self.spec["search_append_year"] and not season:
                from quasarr.providers.imdb_metadata import get_year

                year = get_year(imdb_id)
                if year:
                    title += f" {year}"
            return html.unescape(title) if title else None, imdb_id
        return None, imdb_id

    def search(
        self,
        shared_state,
        start_time,
        search_category,
        search_string="",
        season=None,
        episode=None,
        episode_date=None,
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
                episode_date=episode_date,
            )
        from quasarr.providers.utils import (
            date_numbering_title_search_strings,
            get_base_search_category_id,
            is_valid_release,
        )

        try:
            category = get_base_search_category_id(search_category) or search_category
            if int(category) not in self.spec["search_categories"]:
                return []
            query, imdb_id = self._search_query(
                shared_state, start_time, search_category, search_string, season
            )
            if not query:
                return []
            if episode_date is not None and not self.supports_date_numbering:
                episode_date = None
            request_query = (
                date_numbering_title_search_strings(query)[0] if episode_date else query
            )
            if self.spec["search_episode_query"] and season:
                request_query += f" S{int(season):02d}"
                if episode:
                    request_query += f"E{int(episode):02d}"
            match_string = (
                query if self.spec["search_match"] == "query" else search_string
            )

            requests_ = self.search_requests(request_query, category)
            if self.spec["search_follow"]:
                requests_ = self._followed_pages(shared_state, requests_)
                if not requests_:
                    return []
            with ThreadPoolExecutor(max_workers=len(requests_)) as pool:
                pages = list(
                    pool.map(
                        lambda request: self.load_listing(
                            shared_state,
                            request[0],
                            self.spec["search_list"],
                            SEARCH_REQUEST_TIMEOUT_SECONDS,
                            request[1],
                        ),
                        requests_,
                    )
                )
            found = []
            for report, fetched in pages:
                if fetched.error:
                    mark_hostname_issue(self.initials, "search", fetched.error)
                    continue
                self._log_report("Search", report)
                found += report["rows"]
            if not any(fetched.error is None for _, fetched in pages):
                return []
            clear_hostname_issue(self.initials)

            rows = []
            seen = set()
            identity = self.spec["imdb_identity"]
            for row in found:
                if len(pages) > 1 and row["link"] in seen:
                    continue
                if (
                    identity in ("strict", "strict_fill")
                    and imdb_id
                    and row["imdb_id"]
                    and row["imdb_id"] != imdb_id
                ):
                    continue
                if not is_valid_release(
                    row["title"],
                    search_category,
                    match_string,
                    season,
                    episode,
                    episode_date,
                ):
                    continue
                if not passes_search_filters(
                    row["title"], self.spec["search_filters"], search_string
                ):
                    continue
                seen.add(row["link"])
                row = {**row, "title": self._magazine(row["title"], category)}
                if imdb_id and (
                    identity in ("fill", "strict_fill")
                    or (identity == "strict" and not row["imdb_id"])
                ):
                    row["imdb_id"] = imdb_id
                rows.append(row)
            return self._releases(shared_state, rows)
        except Exception as e:
            mark_hostname_issue(self.initials, "search", str(e))
            return []
        finally:
            debug(f"Time taken: {time.time() - start_time:.2f}s")

    def load_download_links(self, shared_state, url):
        """Fetch one release page; returns (links, error, status, imdb_id)."""
        if not _is_on_host(url, self.hostname):
            return [], "Release page is not on this site", None, None
        download = self.spec["download"]
        if not (download["selector"] or download["container"] or download["section"]):
            return [], "No download links configured", None, None
        fetched = fetch_markup(
            shared_state,
            url,
            DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            self.spec["flaresolverr"],
        )
        if fetched.error:
            return [], fetched.error, fetched.status, None
        links = parse_download_links(fetched.markup, url, download, self.hostname)
        if links is None:
            return [], "Could not find main content section", fetched.status, None
        imdb_id = page_imdb_id(fetched.markup) if download["imdb"] else None
        if self.spec["download"]["redirects"]:
            links = self._resolve_redirects(shared_state, links)
        return (
            links,
            None if links else "No download links matched",
            fetched.status,
            imdb_id,
        )

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
                    accept_offsite=self.spec["download"]["redirect_targets"] == "any",
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
            links, link_error, status, imdb_id = self.load_download_links(
                shared_state, url
            )
            download = self.spec["download"]
            result = {"links": []}
            if imdb_id:
                result["imdb_id"] = imdb_id
            if status == 404:
                # a removed release, not a broken site
                info(f"Release page for {title} no longer exists")
                return result
            if link_error:
                empty = link_error == "No download links matched"
                if (status is not None or "Request failed" in link_error) and (
                    download["empty_is_issue"] or not empty
                ):
                    mark_hostname_issue(self.initials, "download", link_error)
                return result
            if mirrors and download["filter_mirrors"] == "exact":
                wanted = {normalize_hoster_name(m) for m in mirrors if m}
                links = [link for link in links if link[1] in wanted]
            elif mirrors and download["filter_mirrors"] != "none":
                index = 1 if download["filter_mirrors"] == "mirror" else 0
                links = [
                    link
                    for link in links
                    if any(m.lower() in link[index].lower() for m in mirrors)
                ]
                if not links:
                    info(f"No download links for {title} match the mirrors {mirrors}")
                    return result
            clear_hostname_issue(self.initials)
            return {**result, "links": links}
        except Exception as e:
            mark_hostname_issue(self.initials, "download", str(e))
            return {"links": []}

    def get_package_identity(self, url):
        if "package_identity" in self.hooks:
            return self.hooks["package_identity"](self, url)
        return None
