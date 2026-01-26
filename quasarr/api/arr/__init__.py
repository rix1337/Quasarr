# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import traceback
import xml.sax.saxutils as sax_utils
from base64 import urlsafe_b64decode
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

from bottle import abort, request

from quasarr.downloads import download
from quasarr.downloads.packages import delete_package, get_packages
from quasarr.providers import shared_state
from quasarr.providers.auth import require_api_key
from quasarr.providers.log import debug, info
from quasarr.providers.version import get_version
from quasarr.search import get_search_results


def parse_payload(payload_str):
    """
    Parse the base64-encoded payload string into its components.

    Supports both legacy 6-field format and new 7-field format:
    - Legacy (6 fields): title|url|mirror|size_mb|password|imdb_id
    - New (7 fields): title|url|mirror|size_mb|password|imdb_id|source_key

    Returns:
        dict with keys: title, url, mirror, size_mb, password, imdb_id, source_key
    """
    decoded = urlsafe_b64decode(payload_str.encode()).decode()
    parts = decoded.split("|")

    if len(parts) == 6:
        # Legacy format - no source_key provided
        title, url, mirror, size_mb, password, imdb_id = parts
        source_key = None
    elif len(parts) == 7:
        # New format with source_key
        title, url, mirror, size_mb, password, imdb_id, source_key = parts
    else:
        raise ValueError(f"expected 6 or 7 fields, got {len(parts)}")

    return {
        "title": title,
        "url": url,
        "mirror": None if mirror == "None" else mirror,
        "size_mb": size_mb,
        "password": password if password else None,
        "imdb_id": imdb_id if imdb_id else None,
        "source_key": source_key if source_key else None,
    }


def setup_arr_routes(app):
    @app.get("/download/")
    def fake_nzb_file():
        payload = request.query.payload
        decoded_payload = urlsafe_b64decode(payload).decode("utf-8").split("|")

        # Support both 6 and 7 field formats
        title = decoded_payload[0]
        url = decoded_payload[1]
        mirror = decoded_payload[2]
        size_mb = decoded_payload[3]
        password = decoded_payload[4]
        imdb_id = decoded_payload[5]
        source_key = decoded_payload[6] if len(decoded_payload) > 6 else ""

        return f'<nzb><file title="{title}" url="{url}" mirror="{mirror}" size_mb="{size_mb}" password="{password}" imdb_id="{imdb_id}" source_key="{source_key}"/></nzb>'

    @app.post("/api")
    @require_api_key
    def download_fake_nzb_file():
        downloads = request.files.getall("name")
        nzo_ids = []  # naming structure for package IDs expected in newznab

        for upload in downloads:
            file_content = upload.file.read()
            root = ElementTree.fromstring(file_content)

            title = sax_utils.unescape(root.find(".//file").attrib["title"])

            url = root.find(".//file").attrib["url"]
            mirror = (
                None
                if (mirror := root.find(".//file").attrib.get("mirror")) == "None"
                else mirror
            )

            size_mb = root.find(".//file").attrib["size_mb"]
            password = root.find(".//file").attrib.get("password")
            imdb_id = root.find(".//file").attrib.get("imdb_id")
            source_key = root.find(".//file").attrib.get("source_key") or None

            info(f'Attempting download for "{title}"')
            request_from = request.headers.get("User-Agent")
            downloaded = download(
                shared_state,
                request_from,
                title,
                url,
                mirror,
                size_mb,
                password,
                imdb_id,
                source_key,
            )
            try:
                success = downloaded["success"]
                package_id = downloaded["package_id"]
                title = downloaded["title"]

                if success:
                    info(f'"{title}" added successfully!')
                else:
                    info(f'"{title}" added unsuccessfully! See log for details.')
                nzo_ids.append(package_id)
            except KeyError:
                info(f'Failed to download "{title}" - no package_id returned')

        return {"status": True, "nzo_ids": nzo_ids}

    @app.get("/api")
    @app.get("/api/<mirror>")
    @require_api_key
    def quasarr_api(mirror=None):
        api_type = (
            "arr_download_client"
            if request.query.mode
            else "arr_indexer"
            if request.query.t
            else None
        )

        if api_type == "arr_download_client":
            # This builds a mock SABnzbd API response based on the My JDownloader integration
            try:
                mode = request.query.mode
                if mode == "auth":
                    return {"auth": "apikey"}
                elif mode == "version":
                    return {"version": f"Quasarr {get_version()}"}
                elif mode == "get_cats":
                    return {"categories": ["*", "movies", "tv", "docs"]}
                elif mode == "get_config":
                    return {
                        "config": {
                            "misc": {"quasarr": True, "complete_dir": "/tmp/"},
                            "categories": [
                                {
                                    "name": "*",
                                    "order": 0,
                                    "dir": "",
                                },
                                {
                                    "name": "movies",
                                    "order": 1,
                                    "dir": "",
                                },
                                {
                                    "name": "tv",
                                    "order": 2,
                                    "dir": "",
                                },
                                {
                                    "name": "docs",
                                    "order": 3,
                                    "dir": "",
                                },
                            ],
                        }
                    }
                elif mode == "fullstatus":
                    return {"status": {"quasarr": True}}
                elif mode == "addurl":
                    raw_name = getattr(request.query, "name", None)
                    if not raw_name:
                        abort(400, "missing or empty 'name' parameter")

                    payload = False
                    try:
                        parsed = urlparse(raw_name)
                        qs = parse_qs(parsed.query)
                        payload = qs.get("payload", [None])[0]
                    except Exception as e:
                        abort(400, f"invalid URL in 'name': {e}")
                    if not payload:
                        abort(400, "missing 'payload' parameter in URL")

                    try:
                        parsed_payload = parse_payload(payload)
                    except Exception as e:
                        abort(400, f"invalid payload format: {e}")

                    nzo_ids = []
                    info(f'Attempting download for "{parsed_payload["title"]}"')
                    request_from = "lazylibrarian"

                    downloaded = download(
                        shared_state,
                        request_from,
                        parsed_payload["title"],
                        parsed_payload["url"],
                        parsed_payload["mirror"],
                        parsed_payload["size_mb"],
                        parsed_payload["password"],
                        parsed_payload["imdb_id"],
                        parsed_payload["source_key"],
                    )

                    try:
                        success = downloaded["success"]
                        package_id = downloaded["package_id"]
                        title = downloaded.get("title", parsed_payload["title"])

                        if success:
                            info(f'"{title}" added successfully!')
                        else:
                            info(
                                f'"{title}" added unsuccessfully! See log for details.'
                            )
                        nzo_ids.append(package_id)
                    except KeyError:
                        info(
                            f'Failed to download "{parsed_payload["title"]}" - no package_id returned'
                        )

                    return {"status": True, "nzo_ids": nzo_ids}

                elif mode == "queue" or mode == "history":
                    if request.query.name and request.query.name == "delete":
                        package_id = request.query.value
                        deleted = delete_package(shared_state, package_id)
                        return {"status": deleted, "nzo_ids": [package_id]}

                    packages = get_packages(shared_state)
                    if mode == "queue":
                        return {
                            "queue": {
                                "paused": False,
                                "slots": packages.get("queue", []),
                            }
                        }
                    elif mode == "history":
                        return {
                            "history": {
                                "paused": False,
                                "slots": packages.get("history", []),
                            }
                        }
            except Exception as e:
                info(f"Error loading packages: {e}")
                info(traceback.format_exc())
            info(f"[ERROR] Unknown download client request: {dict(request.query)}")
            return {"status": False}

        elif api_type == "arr_indexer":
            # this builds a mock Newznab API response based on Quasarr search
            try:
                if mirror:
                    debug(
                        f'Search will only return releases that match this mirror: "{mirror}"'
                    )

                mode = request.query.t
                request_from = request.headers.get("User-Agent")

                if mode == "caps":
                    info(f"Providing indexer capability information to {request_from}")
                    return """<?xml version="1.0" encoding="UTF-8"?>
                                <caps>
                                  <server 
                                    version="1.33.7" 
                                    title="Quasarr" 
                                    url="https://quasarr.indexer/" 
                                    email="support@quasarr.indexer" 
                                  />
                                  <limits max="9999" default="9999" />
                                  <registration available="no" open="no" />
                                  <searching>
                                    <search available="yes" supportedParams="q" />
                                    <tv-search available="yes" supportedParams="imdbid,season,ep" />
                                    <movie-search available="yes" supportedParams="imdbid" />
                                  </searching>
                                  <categories>
                                    <category id="5000" name="TV" />
                                    <category id="2000" name="Movies" />
                                    <category id="7000" name="Books">
                                  </category>
                                  </categories>
                                </caps>"""
                elif mode in ["movie", "tvsearch", "book", "search"]:
                    releases = []

                    try:
                        offset = int(getattr(request.query, "offset", 0))
                    except (AttributeError, ValueError):
                        offset = 0

                    if offset > 0:
                        debug(
                            f"Ignoring offset parameter: {offset} - it leads to redundant requests"
                        )

                    else:
                        if mode == "movie":
                            # supported params: imdbid
                            imdb_id = getattr(request.query, "imdbid", "")

                            releases = get_search_results(
                                shared_state,
                                request_from,
                                imdb_id=imdb_id,
                                mirror=mirror,
                            )

                        elif mode == "tvsearch":
                            # supported params: imdbid, season, ep
                            imdb_id = getattr(request.query, "imdbid", "")
                            season = getattr(request.query, "season", None)
                            episode = getattr(request.query, "ep", None)
                            releases = get_search_results(
                                shared_state,
                                request_from,
                                imdb_id=imdb_id,
                                mirror=mirror,
                                season=season,
                                episode=episode,
                            )
                        elif mode == "book":
                            author = getattr(request.query, "author", "")
                            title = getattr(request.query, "title", "")
                            search_phrase = " ".join(filter(None, [author, title]))
                            releases = get_search_results(
                                shared_state,
                                request_from,
                                search_phrase=search_phrase,
                                mirror=mirror,
                            )

                        elif mode == "search":
                            if "lazylibrarian" in request_from.lower():
                                search_phrase = getattr(request.query, "q", "")
                                releases = get_search_results(
                                    shared_state,
                                    request_from,
                                    search_phrase=search_phrase,
                                    mirror=mirror,
                                )
                            else:
                                info(
                                    f"Ignoring search request from {request_from} - only imdbid searches are supported"
                                )
                                releases = []  # sonarr expects this but we will not support non-imdbid searches

                    items = ""
                    for release in releases:
                        release = release.get("details", {})

                        # Ensure clean XML output
                        title = sax_utils.escape(release.get("title", ""))
                        source = sax_utils.escape(release.get("source", ""))

                        if not "lazylibrarian" in request_from.lower():
                            title = f"[{release.get('hostname', '').upper()}] {title}"

                        # Get publication date - sources should provide valid dates
                        pub_date = release.get("date", "").strip()

                        items += f'''
                        <item>
                            <title>{title}</title>
                            <guid isPermaLink="True">{release.get("link", "")}</guid>
                            <link>{release.get("link", "")}</link>
                            <comments>{source}</comments>
                            <pubDate>{pub_date}</pubDate>
                            <enclosure url="{release.get("link", "")}" length="{release.get("size", 0)}" type="application/x-nzb" />
                        </item>'''

                    requires_placeholder_item = not getattr(
                        request.query, "imdbid", ""
                    ) and not getattr(request.query, "q", "")
                    if requires_placeholder_item and not items:
                        items = f"""
                        <item>
                            <title>No results found</title>
                            <guid isPermaLink="False">0</guid>
                            <link>https://github.com/rix1337/Quasarr</link>
                            <comments>No results matched your search criteria.</comments>
                            <pubDate>{datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
                            <enclosure url="https://github.com/rix1337/Quasarr" length="0" type="application/x-nzb" />
                        </item>"""

                    return f"""<?xml version="1.0" encoding="UTF-8"?>
                                <rss>
                                    <channel>
                                        {items}
                                    </channel>
                                </rss>"""
            except Exception as e:
                info(f"Error loading search results: {e}")
                info(traceback.format_exc())
            info(f"[ERROR] Unknown indexer request: {dict(request.query)}")
            return """<?xml version="1.0" encoding="UTF-8"?>
                        <rss>
                            <channel>
                                <title>Quasarr Indexer</title>
                                <description>Quasarr Indexer API</description>
                                <link>https://quasarr.indexer/</link>
                            </channel>
                        </rss>"""

        info(f"[ERROR] Unknown general request: {dict(request.query)}")
        return {"error": True}
