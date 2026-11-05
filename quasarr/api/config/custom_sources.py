# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import time
from urllib.parse import urlparse

from bottle import request, response

from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.providers.auth import require_api_key
from quasarr.search.sources.helpers.custom_source import (
    CustomSource,
    DefinitionError,
    _compile_listing,
    _is_on_host,
    _normalize_hostname,
    describe_report,
    fetch_markup,
)
from quasarr.search.sources.helpers.custom_suggest import (
    MIN_ITEMS,
    builtin_matches,
    detect_templates,
    discover_search,
    export_template,
    listing_from_suggestion,
    search_quality,
    suggest_download,
    suggest_listing,
)
from quasarr.search.sources.templates import get_template_definitions
from quasarr.storage.custom_sources import (
    delete_definition,
    load_definitions,
    save_definition,
)

# Drafts are previewed before they own a key; nothing is stored under it.
_PREVIEW_KEY = "c1"


def _draft_source(definition):
    draft = dict(definition or {})
    draft["key"] = draft.get("key") or _PREVIEW_KEY
    return CustomSource(draft)


def _fail(message, status=400):
    response.status = status
    return {"success": False, "error": message}


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

    @app.get("/api/custom-sources/templates")
    @require_api_key
    def list_bundled_templates():
        """Bundled templates to copy into a custom source; hooks do not copy."""
        response.content_type = "application/json"
        templates = []
        for key, definition in get_template_definitions().items():
            copyable = not definition.get("hooks")
            templates.append(
                {
                    "key": key.upper(),
                    "name": definition.get("name"),
                    "copyable": copyable,
                    "definition": {
                        k: v
                        for k, v in definition.items()
                        if k not in ("key", "hooks", "capabilities", "categories")
                    }
                    if copyable
                    else None,
                }
            )
        return {"success": True, "templates": templates}

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
            query, _ = source._search_query(
                shared_state, time.time(), category, str(data.get("query") or "")
            )
            if not query:
                return _fail("No search term for this query")
            url, form = source.search_request(query)
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
        payload = {
            "url": url,
            "suggest_flaresolverr": suggest,
            **_report_payload(report),
        }
        if data.get("step") == "search":
            payload["quality"] = search_quality(query, report["rows"])
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
            hostname = _normalize_hostname(data.get("hostname"))
        except DefinitionError as e:
            return _fail(str(e))
        url = str(data.get("url") or "/").strip()
        if url.startswith("/"):
            url = f"https://{hostname}{url}"
        if urlparse(url).scheme not in ("http", "https") or not _is_on_host(
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

    @app.post("/api/custom-sources/suggest-search")
    @require_api_key
    def suggest_custom_source_search():
        """Find a search URL and IMDb support, starting from a working feed."""
        response.content_type = "application/json"
        data = request.json or {}
        try:
            hostname = _normalize_hostname(data.get("hostname"))
            _compile_listing(data.get("list"), "list")
        except DefinitionError as e:
            return _fail(str(e))
        feed_url = str(data.get("feed_url") or "/").strip()
        if feed_url.startswith("/"):
            feed_url = f"https://{hostname}{feed_url}"
        if not _is_on_host(feed_url, hostname):
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
        links, link_error, _ = source.load_download_links(shared_state, url)
        if link_error:
            return {"success": False, "error": link_error}
        return {"success": True, "links": links, "classified": classify_links(links)}
