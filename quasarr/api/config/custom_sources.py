# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import secrets
import threading
import time
from urllib.parse import urlparse

from bottle import request, response

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers.auth import require_api_key
from quasarr.providers.utils import is_imdb_id
from quasarr.search.sources.helpers.custom_source import (
    CustomSource,
    DefinitionError,
    _compile_listing,
    describe_report,
    fetch_markup,
    is_on_host,
    normalize_hostname,
)
from quasarr.search.sources.helpers.custom_suggest import (
    MIN_ITEMS,
    _search_request,
    annotate_page,
    builtin_matches,
    detect_templates,
    discover_search,
    export_template,
    highlight,
    import_template,
    is_feed_markup,
    listing_from_suggestion,
    page_language,
    page_rss,
    pick_download,
    pick_field,
    pick_item,
    preview_html,
    report_table,
    search_quality,
    suggest_download,
    suggest_feeds,
    suggest_listing,
)
from quasarr.storage.custom_sources import (
    delete_definition,
    load_definitions,
    save_definition,
)

# Drafts are previewed before they own a key; nothing is stored under it.
_PREVIEW_KEY = "c1"

# pages loaded in the wizard, so clicks can be turned into selectors
_PAGE_TTL_SECONDS = 20 * 60
_PAGE_LIMIT = 12
_pages = {}
_pages_lock = threading.Lock()


def _store_page(page):
    token = secrets.token_urlsafe(16)
    now = time.time()
    with _pages_lock:
        for old in [t for t, p in _pages.items() if p["expires"] < now]:
            del _pages[old]
        while len(_pages) >= _PAGE_LIMIT:
            del _pages[min(_pages, key=lambda t: _pages[t]["expires"])]
        _pages[token] = {**page, "expires": now + _PAGE_TTL_SECONDS}
    return token


def _page(token):
    with _pages_lock:
        page = _pages.get(str(token or ""))
        if page and page["expires"] >= time.time():
            return page
    return None


def _search_page_request(hostname, search, query):
    """URL and form data of one search, checked like a saved definition."""
    if not isinstance(search, dict):
        raise DefinitionError("search: must be an object")
    query = str(query or "").strip()
    if not query:
        raise DefinitionError("Enter something to search for")
    url = str(search.get("url") or "")
    if url.startswith("/"):
        url = "https://{host}" + url
    candidate = {
        "url": url,
        "method": "post" if search.get("method") == "post" else "get",
        "body": str(search.get("body") or ""),
    }
    if not url.startswith("https://{host}") and not url.startswith("http://{host}"):
        raise DefinitionError("The search address must be on the site")
    if candidate["method"] == "post" and "{q}" not in candidate["body"]:
        raise DefinitionError("The form fields must contain {q}")
    if candidate["method"] == "get" and "{q}" not in url:
        raise DefinitionError("The search address must contain {q}")
    request_url, form = _search_request(candidate, hostname, query)
    if not is_on_host(request_url, hostname):
        raise DefinitionError("The search address must be on the site")
    return request_url, form


def _site_url(data):
    """The hostname and a page URL on it, from a wizard request."""
    hostname = normalize_hostname(data.get("hostname"))
    url = str(data.get("url") or "/").strip()
    if url.startswith("/"):
        url = f"https://{hostname}{url}"
    if urlparse(url).scheme not in ("http", "https") or not is_on_host(url, hostname):
        raise DefinitionError("The page must be on the site's hostname")
    return hostname, url


def _draft_source(definition):
    draft = dict(definition or {})
    draft["key"] = draft.get("key") or _PREVIEW_KEY
    return CustomSource(draft)


def _fail(message, status=400):
    response.status = status
    return {"success": False, "error": message}


_VIDEO_SOURCE = re.compile(
    r"\b(web(-?dl|rip)?|blu-?ray|bdrip|hdtv|dvd(rip)?|remux)\b", re.I
)


def _report_payload(report):
    return {
        "success": True,
        "items": report["items"],
        "rows": report["rows"][:25],
        "parsed": len(report["rows"]),
        "skipped": report["skipped"],
        "warnings": report["warnings"],
        "issue": describe_report(report),
    }


def setup_custom_source_routes(app, shared_state):
    @app.get("/api/custom-sources")
    @require_api_key
    def list_custom_sources():
        response.content_type = "application/json"
        return {"success": True, "sources": list(load_definitions().values())}

    @app.post("/api/custom-sources/import")
    @require_api_key
    def import_shared_template():
        """Check a shared template; the wizard then tests and saves it."""
        response.content_type = "application/json"
        try:
            definition = import_template((request.json or {}).get("text"))
        except DefinitionError as e:
            return _fail(str(e))
        return {"success": True, "definition": definition}

    @app.post("/api/custom-sources")
    @require_api_key
    def save_custom_source():
        response.content_type = "application/json"
        try:
            return {"success": True, "source": save_definition(request.json or {})}
        except (DefinitionError, ValueError) as e:
            return _fail(str(e))

    @app.delete("/api/custom-sources/<key>")
    @require_api_key
    def delete_custom_source(key):
        response.content_type = "application/json"
        if not delete_definition(key):
            return _fail(f"Unknown custom source {key}", 404)
        return {"success": True}

    @app.get("/api/custom-sources/<key>/export")
    @require_api_key
    def export_custom_source(key):
        """Template module for a PR, once the live feed and search work."""
        response.content_type = "application/json"
        definition = load_definitions().get(str(key).lower())
        if not definition:
            return _fail(f"Unknown custom source {key}", 404)
        try:
            return export_template(shared_state, definition)
        except DefinitionError as e:
            return _fail(str(e))

    @app.post("/api/custom-sources/preview")
    @require_api_key
    def preview_custom_source():
        """Run feed or search of an unsaved draft and report every item."""
        response.content_type = "application/json"
        data = request.json or {}
        try:
            source = _draft_source(data.get("definition"))
        except DefinitionError as e:
            return _fail(str(e))

        spec = source.spec
        if data.get("step") == "search":
            if not spec["search_url"]:
                return _fail("Search is not enabled")
            category = int(data.get("category") or spec["search_categories"][0])
            raw_query = str(data.get("query") or "").strip()
            query, _ = source._search_query(
                shared_state, time.time(), category, raw_query
            )
            if not query and spec["search_mode"] == "title":
                # a typed title stands in for the one Quasarr looks up by IMDb ID
                query = raw_query
            if not query:
                return _fail(
                    "This search only takes IMDb IDs such as tt0111161"
                    if spec["search_mode"] == "imdb"
                    else "Quasarr could not find a title for this IMDb ID"
                )
            # a kind with its own search section is asked there
            url, form = source.search_requests(query, category)[0]
            if spec["search_follow"]:
                # the results link the posts that hold the releases, as a real search opens them
                followed = source._followed_pages(shared_state, [(url, form)])
                if not followed:
                    return {
                        "success": True,
                        "url": url,
                        "items": 0,
                        "rows": [],
                        "parsed": 0,
                        "skipped": {},
                        "warnings": [],
                        "issue": None,
                        "table": [],
                        "quality": search_quality(query, []),
                        "query": query,
                    }
                url, form = followed[0]
            listing = spec["search_list"]
            timeout = SEARCH_REQUEST_TIMEOUT_SECONDS
        else:
            category = int(data.get("category") or next(iter(spec["feeds"]), 0))
            template = spec["feeds"].get(category)
            if not template:
                return _fail("No feed for this category")
            url = source._url(template)
            form = None
            listing = spec["list"]
            timeout = FEED_REQUEST_TIMEOUT_SECONDS

        report, fetched = source.load_listing(shared_state, url, listing, timeout, form)
        # suggest the toggle so the site does not depend on a 24h fallback
        suggest = fetched.blocked and not spec["flaresolverr"]
        if fetched.error:
            return {
                "success": False,
                "url": url,
                "error": fetched.error,
                "suggest_flaresolverr": suggest,
            }
        table = report_table(fetched.markup, url, listing, source.hostname, report)
        if data.get("step") == "search":
            # what Radarr or Sonarr would get: the same release check as a real search
            from quasarr.constants import CODEC_REGEX, RESOLUTION_REGEX
            from quasarr.providers.utils import is_valid_release

            match = query if spec["search_match"] == "query" else raw_query
            kind = {2000: "movie", 5000: "TV"}.get(category)
            skipped = dict(report["skipped"])
            for row in table:
                if not kind or "skipped" in row:
                    continue
                title = row["title"]
                # a video release names its resolution, codec or source
                video = (
                    RESOLUTION_REGEX.search(title)
                    or CODEC_REGEX.search(title)
                    or _VIDEO_SOURCE.search(title)
                )
                if not video or not is_valid_release(
                    title, category, match, None, None
                ):
                    row["skipped"] = f"not a {kind} release"
                    skipped[row["skipped"]] = skipped.get(row["skipped"], 0) + 1
            report = {
                **report,
                "rows": [r for r in table if "skipped" not in r],
                "skipped": skipped,
            }
        payload = {
            "url": url,
            "suggest_flaresolverr": suggest,
            **_report_payload(report),
            "table": table,
        }
        if data.get("step") == "search":
            # names never carry the IMDb ID: its title tells whether a result is the one
            named = query
            if spec["search_mode"] == "imdb" and is_imdb_id(query):
                from quasarr.providers.imdb_metadata import get_localized_title

                named = (
                    get_localized_title(shared_state, query, spec["language"], category)
                    or get_localized_title(shared_state, query, "en", category)
                    or query
                )
            payload["quality"] = search_quality(named, report["rows"], imdb_id=query)
            # what the site was asked for, as a title looked up from an IMDb ID
            payload["query"] = query
        return payload

    @app.post("/api/custom-sources/suggest")
    @require_api_key
    def suggest_custom_source():
        """Fetch one page of a site and propose selectors for it.

        ``step`` is ``listing`` (a feed or search page) or ``download`` (a
        release page). Works before any definition exists.
        """
        response.content_type = "application/json"
        data = request.json or {}
        try:
            hostname = normalize_hostname(data.get("hostname"))
        except DefinitionError as e:
            return _fail(str(e))
        url = str(data.get("url") or "/").strip()
        if url.startswith("/"):
            url = f"https://{hostname}{url}"
        if urlparse(url).scheme not in ("http", "https") or not is_on_host(
            url, hostname
        ):
            return _fail("The page must be on the site's hostname")

        use_flaresolverr = bool(data.get("flaresolverr"))
        fetched = fetch_markup(
            shared_state, url, FEED_REQUEST_TIMEOUT_SECONDS, use_flaresolverr
        )
        result = {
            "url": url,
            "builtin": builtin_matches(hostname),
            "suggest_flaresolverr": fetched.blocked and not use_flaresolverr,
        }
        if fetched.error:
            return {**result, "success": False, "error": fetched.error}
        if data.get("step") != "download":
            result["templates"] = detect_templates(
                shared_state, fetched.markup, url, hostname
            )
        if data.get("step") == "download":
            return {
                **result,
                "success": True,
                "download": suggest_download(fetched.markup, url, hostname),
            }
        suggestion = suggest_listing(
            fetched.markup,
            url,
            hostname,
            item_selector=data.get("item_selector") or None,
            min_items=1 if data.get("search_page") else MIN_ITEMS,
        )
        listing = (
            listing_from_suggestion(suggestion["best"]) if suggestion["best"] else None
        )
        return {**result, "success": True, **suggestion, "listing": listing}

    @app.post("/api/custom-sources/page")
    @require_api_key
    def load_custom_source_page():
        """Load one page for the wizard: a safe preview plus suggestions.

        ``purpose`` is ``listing`` (feed), ``search`` (one search result page)
        or ``download`` (a release page).
        """
        response.content_type = "application/json"
        data = request.json or {}
        form = None
        try:
            hostname, url = _site_url(data)
            search = data.get("search")
            if search:
                # a results page, requested the way the source will request it
                url, form = _search_page_request(hostname, search, data.get("query"))
        except DefinitionError as e:
            return _fail(str(e))
        purpose = data.get("purpose", "listing")
        use_flaresolverr = bool(data.get("flaresolverr"))
        fetched = fetch_markup(
            shared_state, url, FEED_REQUEST_TIMEOUT_SECONDS, use_flaresolverr, form
        )
        result = {
            "url": url,
            "builtin": builtin_matches(hostname),
            "suggest_flaresolverr": fetched.blocked and not use_flaresolverr,
        }
        if fetched.error:
            return {**result, "success": False, "error": fetched.error}

        soup = annotate_page(fetched.markup)
        token = _store_page({"soup": soup, "url": url, "hostname": hostname})
        feed = is_feed_markup(fetched.markup)
        result.update(
            {
                "success": True,
                "token": token,
                "is_feed": feed,
                # RSS needs no picking; its fields are fixed
                "preview": None if feed else preview_html(soup, url),
            }
        )
        if purpose == "download":
            result["download"] = suggest_download(fetched.markup, url, hostname)
            return result
        suggestion = suggest_listing(
            fetched.markup,
            url,
            hostname,
            min_items=1 if purpose == "search" else MIN_ITEMS,
        )
        result.update(suggestion)
        result["listing"] = (
            listing_from_suggestion(suggestion["best"]) if suggestion["best"] else None
        )
        if purpose == "listing":
            result["feeds"] = suggest_feeds(
                soup, url, hostname, str(data.get("language") or "")
            )
            result["rss"] = None if feed else page_rss(soup, url, hostname)
            result["language"] = None if feed else page_language(soup)
            result["templates"] = detect_templates(
                shared_state, fetched.markup, url, hostname
            )
        return result

    @app.post("/api/custom-sources/pick")
    @require_api_key
    def pick_custom_source_element():
        """Turn a click in the preview into a selector."""
        response.content_type = "application/json"
        data = request.json or {}
        page = _page(data.get("token"))
        if page is None:
            return _fail("The page expired. Load it again.", 410)
        try:
            q = int(data.get("q"))
        except (TypeError, ValueError):
            return _fail("No element was clicked")
        if data.get("kind") == "download":
            picked = pick_download(page["soup"], q, page["url"], page["hostname"])
            if picked.get("error"):
                return _fail(picked["error"])
            return {"success": True, **picked}
        if data.get("kind") == "item":
            picked = pick_item(page["soup"], q, page["url"], page["hostname"])
            if picked is None:
                return _fail("The page changed. Load it again.")
            if picked.get("error"):
                return _fail(picked["error"])
            marked = highlight(page["soup"], picked["selector"], {})
            return {"success": True, **picked, "marked": marked}
        field = str(data.get("field") or "")
        if field not in ("title", "link", "size", "date", "imdb", "source"):
            return _fail("Unknown field")
        picked = pick_field(
            page["soup"],
            q,
            str(data.get("item_selector") or ""),
            field,
            page["url"],
            page["hostname"],
        )
        if picked.get("error"):
            return _fail(picked["error"])
        return {"success": True, **picked}

    @app.post("/api/custom-sources/highlight")
    @require_api_key
    def highlight_custom_source_page():
        """Element numbers that selectors match, for outlining the preview."""
        response.content_type = "application/json"
        data = request.json or {}
        page = _page(data.get("token"))
        if page is None:
            return _fail("The page expired. Load it again.", 410)
        fields = data.get("fields") or {}
        options = data.get("options") or {}
        if not isinstance(fields, dict) or not isinstance(options, dict):
            return _fail("Fields must be an object")
        marked = highlight(
            page["soup"],
            str(data.get("item_selector") or ""),
            fields,
            page["url"],
            page["hostname"],
            options,
        )
        if marked.get("error"):
            return _fail(marked["error"])
        return {"success": True, **marked}

    @app.post("/api/custom-sources/imdb-lookup")
    @require_api_key
    def lookup_imdb_titles():
        """Movies or shows by title or IMDb ID, through Radarr or Sonarr."""
        response.content_type = "application/json"
        data = request.json or {}
        term = str(data.get("term") or "").strip()[:100]
        shows = data.get("kind") == "tv"
        if shows:
            from quasarr.providers.sonarr_api import get_client
        else:
            from quasarr.providers.radarr_api import get_client
        client = get_client(shared_state)
        if client is None:
            return _fail(f"{'Sonarr' if shows else 'Radarr'} is not set up")
        if not term:
            return {"success": True, "results": []}
        if re.fullmatch(r"tt\d{5,10}", term):
            term = f"imdb:{term}"
        found = client.series_lookup(term) if shows else client.movie_lookup(term)
        results = [
            {
                "imdb_id": item["imdbId"],
                "title": item.get("title"),
                "year": item.get("year"),
            }
            for item in found or []
            if item.get("imdbId")
        ]
        return {"success": True, "results": results[:8]}

    @app.post("/api/custom-sources/suggest-search")
    @require_api_key
    def suggest_custom_source_search():
        """Find a search URL and IMDb support, starting from a working feed."""
        response.content_type = "application/json"
        data = request.json or {}
        try:
            hostname = normalize_hostname(data.get("hostname"))
            _compile_listing(data.get("list"), "list")
        except DefinitionError as e:
            return _fail(str(e))
        feed_url = str(data.get("feed_url") or "/").strip()
        if feed_url.startswith("/"):
            feed_url = f"https://{hostname}{feed_url}"
        if not is_on_host(feed_url, hostname):
            return _fail("The feed must be on the site's hostname")
        return discover_search(shared_state, hostname, feed_url, data["list"])

    @app.post("/api/custom-sources/test-download")
    @require_api_key
    def test_custom_source_download():
        """Extract download links of one release page with an unsaved draft."""
        from quasarr.downloads import classify_links

        response.content_type = "application/json"
        data = request.json or {}
        try:
            source = _draft_source(data.get("definition"))
        except DefinitionError as e:
            return _fail(str(e))
        url = str(data.get("url") or "")
        links, link_error, _, _ = source.load_download_links(shared_state, url)
        if link_error:
            return {"success": False, "error": link_error}
        return {"success": True, "links": links, "classified": classify_links(links)}
