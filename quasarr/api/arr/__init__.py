# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import traceback
import xml.sax.saxutils as sax_utils
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

from bottle import request

from quasarr.downloads import download
from quasarr.downloads.packages import delete_package, get_packages
from quasarr.providers import shared_state
from quasarr.providers.auth import require_api_key
from quasarr.providers.log import debug, error, info, warn
from quasarr.providers.utils import (
    determine_category,
    determine_search_categories,
    extract_client_type,
    format_search_cache_family_groups,
    get_search_cache_family_groups,
    has_source_capability_for_category,
    order_search_categories_for_execution,
    parse_payload,
)
from quasarr.providers.version import get_version
from quasarr.search import get_search_results
from quasarr.search.sources import get_sources
from quasarr.storage.categories import get_download_categories, get_search_categories


def _get_release_dedupe_key(release):
    details = release.get("details", {}) if isinstance(release, dict) else {}

    link = str(details.get("link", "") or "").strip()
    if not link:
        return None
    return ("link", link)


def _dedupe_releases(releases):
    deduped = []
    seen = set()
    removed = 0

    for release in releases:
        key = _get_release_dedupe_key(release)
        if key is None:
            # Be conservative: keep entries without stable identity.
            deduped.append(release)
            continue
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        deduped.append(release)

    return deduped, removed


def _xml_text(value):
    return sax_utils.escape(str(value or ""))


def _xml_attr(value):
    return sax_utils.quoteattr(str(value or ""))


def setup_arr_routes(app):
    @app.get("/download/")
    @require_api_key
    def fake_nzb_file():
        payload = request.query.payload
        decoded_payload = parse_payload(payload)

        title = decoded_payload["title"]
        url = decoded_payload["url"]
        size_mb = decoded_payload["size_mb"]
        password = decoded_payload["password"] or ""
        imdb_id = decoded_payload["imdb_id"] or ""
        source_key = decoded_payload["source_key"] or ""

        # title/url/password can carry XML-significant characters (e.g. "&" in
        # 1Fichier URLs, quotes/accents in French titles), so escape those via
        # the shared helper. size_mb/imdb_id/source_key are constrained values
        # that never contain such characters.
        return (
            f"<nzb><file title={_xml_attr(title)} url={_xml_attr(url)} "
            f'size_mb="{size_mb}" password={_xml_attr(password)} '
            f'imdb_id="{imdb_id}" source_key="{source_key}"/></nzb>'
        )

    @app.post("/api")
    @require_api_key
    def download_fake_nzb_file():
        request_from = request.headers.get("User-Agent") or ""
        downloads = request.files.getall("name")
        nzo_ids = []  # naming structure for package IDs expected in newznab

        for upload in downloads:
            file_content = upload.file.read()
            root = ElementTree.fromstring(file_content)

            title = sax_utils.unescape(root.find(".//file").attrib["title"])

            url = root.find(".//file").attrib["url"]

            size_mb = root.find(".//file").attrib["size_mb"]
            password = root.find(".//file").attrib.get("password")
            imdb_id = root.find(".//file").attrib.get("imdb_id")
            source_key = root.find(".//file").attrib.get("source_key") or None

            # Extract category from request, SABnzbd addfile expects &cat=...
            category_param = getattr(request.query, "cat", None)
            download_category = determine_category(request_from, category_param)

            info(f"Attempting download for <y>{title}</y>")
            try:
                downloaded = download(
                    shared_state,
                    request_from,
                    download_category,
                    title,
                    url,
                    size_mb,
                    password,
                    imdb_id,
                    source_key,
                )
            except Exception as e:
                if type(e).__name__ == "TokenExpiredException":
                    warn(
                        f"Download failed for <y>{title}</y>: MyJDownloader token expired."
                    )
                    continue
                raise e
            try:
                success = downloaded["success"]
                package_id = downloaded["package_id"]
                title = downloaded["title"]
                failed = downloaded.get("failed", False)

                if success and not failed:
                    info(f"<y>{title}</y> added successfully!")
                else:
                    info(
                        f"<y>{title}</y> added as failed package! See log for details."
                    )

                nzo_ids.append(package_id)
            except KeyError:
                info(f"Failed to download <y>{title}</y> - no package_id returned")

        response = {"status": True, "nzo_ids": nzo_ids}
        if not nzo_ids:
            response["quasarr_error"] = True
        return response

    @app.get("/api")
    @require_api_key
    def quasarr_api():
        request_from = request.headers.get("User-Agent") or ""

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
                    # Dynamic categories
                    cats = get_download_categories()
                    # SABnzbd usually returns '*' as the first category
                    if "*" not in cats:
                        cats.insert(0, "*")
                    return {"categories": cats}
                elif mode == "get_config":
                    # Dynamic categories for config
                    cats = get_download_categories()
                    cat_configs = [{"name": "*", "order": 0, "dir": ""}]
                    for i, cat in enumerate(cats):
                        if cat == "*":
                            continue
                        cat_configs.append({"name": cat, "order": i + 1, "dir": ""})

                    return {
                        "config": {
                            "misc": {"quasarr": True, "complete_dir": "/tmp/"},
                            "categories": cat_configs,
                        }
                    }
                elif mode == "fullstatus":
                    return {"status": {"quasarr": True}}
                elif mode == "addurl":
                    raw_name = getattr(request.query, "name", None)
                    if not raw_name:
                        # SABnzbd returns status: False if name is missing
                        return {"status": False, "nzo_ids": [], "quasarr_error": True}

                    # Extract category from request, SABnzbd addurl expects &cat=...
                    category_param = getattr(request.query, "cat", None)
                    download_category = determine_category(request_from, category_param)

                    try:
                        parsed = urlparse(raw_name)
                        qs = parse_qs(parsed.query)
                        payload = qs.get("payload", [None])[0]
                    except Exception as e:
                        info(f"Invalid URL in 'name': {e}")
                        return {"status": False, "nzo_ids": [], "quasarr_error": True}
                    if not payload:
                        info("Missing 'payload' parameter in URL")
                        return {"status": False, "nzo_ids": [], "quasarr_error": True}

                    try:
                        parsed_payload = parse_payload(payload)
                    except Exception as e:
                        info(f"Invalid payload format: {e}")
                        return {"status": False, "nzo_ids": [], "quasarr_error": True}

                    nzo_ids = []
                    info(f"Attempting download for <y>{parsed_payload['title']}</y>")

                    downloaded = download(
                        shared_state,
                        request_from,
                        download_category,
                        parsed_payload["title"],
                        parsed_payload["url"],
                        parsed_payload["size_mb"],
                        parsed_payload["password"],
                        parsed_payload["imdb_id"],
                        parsed_payload["source_key"],
                    )

                    try:
                        success = downloaded["success"]
                        package_id = downloaded["package_id"]
                        title = downloaded.get("title", parsed_payload["title"])
                        failed = downloaded.get("failed", False)

                        if success and not failed:
                            info(f'"{title} added successfully!')
                        else:
                            info(
                                f'"{title} added as failed package! See log for details.'
                            )

                        nzo_ids.append(package_id)
                        return {"status": True, "nzo_ids": nzo_ids}
                    except KeyError:
                        info(
                            f'Failed to download "{parsed_payload["title"]}" - no package_id returned'
                        )
                        return {"status": True, "nzo_ids": [], "quasarr_error": True}

                elif mode == "queue" or mode == "history":
                    if request.query.name and request.query.name == "delete":
                        package_id = request.query.value
                        package_title = getattr(request.query, "title", None) or None
                        deleted = delete_package(
                            shared_state,
                            package_id,
                            package_title=package_title,
                            missing_ok=True,
                        )
                        response = {"status": deleted, "nzo_ids": [package_id]}
                        if not deleted:
                            response["quasarr_error"] = True
                        return response

                    packages = get_packages(shared_state)
                    if mode == "queue":
                        return {
                            "queue": {
                                "paused": False,
                                "slots": packages.get("queue", []),
                                "linkgrabber": packages.get(
                                    "linkgrabber",
                                    {"is_collecting": False, "is_stopped": True},
                                ),
                            }
                        }
                    elif mode == "history":
                        return {
                            "history": {
                                "paused": False,
                                "slots": packages.get("history", []),
                                "linkgrabber": packages.get(
                                    "linkgrabber",
                                    {"is_collecting": False, "is_stopped": True},
                                ),
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
                mode = request.query.t
                if mode == "caps":
                    info(f"Providing indexer capability information to {request_from}")

                    # Generate categories XML dynamically
                    categories_xml = ""
                    all_categories = get_search_categories()

                    # Sort categories by ID for cleaner XML
                    sorted_cats = sorted(
                        all_categories.items(), key=lambda x: int(x[0])
                    )

                    supported_categories_union = set()
                    for source in get_sources().values():
                        supported_categories_union.update(source.supported_categories)

                    for cat_id, details in sorted_cats:
                        if has_source_capability_for_category(
                            cat_id, supported_categories_union
                        ):
                            cat_name = sax_utils.escape(
                                str(details.get("name", cat_id))
                            )
                            categories_xml += (
                                f'<category id="{cat_id}" name="{cat_name}" />\n'
                            )

                    return f"""<?xml version="1.0" encoding="UTF-8"?>
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
                                    {categories_xml}
                                  </categories>
                                </caps>"""

                elif mode in ["movie", "tvsearch", "book", "music", "search"]:
                    releases = []

                    try:
                        offset = int(getattr(request.query, "offset", 0) or 0)
                    except (AttributeError, ValueError) as e:
                        debug(f"Error parsing offset parameter: {e}")
                        offset = 0

                    try:
                        limit = int(getattr(request.query, "limit", 9999) or 9999)
                    except (AttributeError, ValueError) as e:
                        debug(f"Error parsing limit parameter: {e}")
                        limit = 1000

                    # Extract and normalize one or more categories from request
                    requested_cat = getattr(request.query, "cat", None)
                    requested_categories = determine_search_categories(
                        request_from, requested_cat
                    )
                    search_categories = order_search_categories_for_execution(
                        requested_categories
                    )
                    cache_family_groups = get_search_cache_family_groups(
                        requested_categories
                    )

                    if len(search_categories) > 1:
                        debug(
                            "Executing multi-category search request "
                            f"<g>{requested_cat}</g> as categories "
                            f"<g>{','.join(str(cat) for cat in search_categories)}</g> "
                            "with cache groups "
                            f"<g>{format_search_cache_family_groups(cache_family_groups)}</g>"
                        )

                    def run_search_for_categories(search_runner):
                        if not search_categories:
                            return []
                        if len(search_categories) == 1:
                            return search_runner(search_categories[0], offset, limit)

                        # Run each cache-sharing family in sequence to ensure
                        # lower/less-restrictive categories populate cache first.
                        # Different families can run independently.
                        fetch_limit = max(offset + limit, 1000)

                        def run_cache_group(group_categories):
                            group_results = []
                            for category_id in group_categories:
                                group_results.extend(
                                    search_runner(category_id, 0, fetch_limit)
                                )
                            return group_results

                        combined_results = []
                        if len(cache_family_groups) == 1:
                            combined_results = run_cache_group(search_categories)
                        else:
                            group_results = {}
                            with ThreadPoolExecutor(
                                max_workers=len(cache_family_groups)
                            ) as executor:
                                futures = {
                                    executor.submit(
                                        run_cache_group, group_categories
                                    ): owner
                                    for owner, group_categories in cache_family_groups
                                }
                                for future in as_completed(futures):
                                    owner = futures[future]
                                    group_results[owner] = future.result()

                            for owner, _ in cache_family_groups:
                                combined_results.extend(group_results.get(owner, []))

                        deduped_results, removed_duplicates = _dedupe_releases(
                            combined_results
                        )
                        if removed_duplicates > 0:
                            debug(
                                "Removed duplicate releases from multi-category response: "
                                f"<r>{removed_duplicates}</r> duplicate entries filtered"
                            )

                        return deduped_results[offset : offset + limit]

                    if mode in ["movie", "tvsearch"]:
                        imdb_id = getattr(request.query, "imdbid", "")
                        season = getattr(request.query, "season", None)
                        episode = getattr(request.query, "ep", None)
                        q = getattr(request.query, "q", None)
                        supported = False if q else True

                        if q and mode == "tvsearch" and imdb_id:
                            try:
                                episode = int(q)
                                supported = True
                            except:
                                pass

                        if supported:
                            releases = run_search_for_categories(
                                lambda category_id, request_offset, request_limit: (
                                    get_search_results(
                                        shared_state,
                                        request_from,
                                        category_id,
                                        imdb_id=imdb_id,
                                        season=season,
                                        episode=episode,
                                        offset=request_offset,
                                        limit=request_limit,
                                    )
                                )
                            )
                        else:
                            # sonarr expects this but we will not support non-imdbid searches
                            debug(
                                f"Ignoring search request from <d>{request_from}</d> - only imdbid searches are supported"
                            )

                    elif mode in ["book", "music"]:
                        author = getattr(request.query, "author", "")
                        title = getattr(request.query, "title", "")
                        search_phrase = " ".join(filter(None, [author, title]))
                        releases = run_search_for_categories(
                            lambda category_id, request_offset, request_limit: (
                                get_search_results(
                                    shared_state,
                                    request_from,
                                    category_id,
                                    search_phrase=search_phrase,
                                    offset=request_offset,
                                    limit=request_limit,
                                )
                            )
                        )

                    elif mode == "search":
                        if extract_client_type(request_from) in [
                            "magazarr",
                            "lidarr",
                        ]:
                            search_phrase = getattr(request.query, "q", "")
                            releases = run_search_for_categories(
                                lambda category_id, request_offset, request_limit: (
                                    get_search_results(
                                        shared_state,
                                        request_from,
                                        category_id,
                                        search_phrase=search_phrase,
                                        offset=request_offset,
                                        limit=request_limit,
                                    )
                                )
                            )
                        else:
                            debug(
                                f"Unsupported search mode '{mode}' from <d>{request_from}</d>"
                            )

                    else:
                        warn(f"Unknown search mode '{mode}' from <d>{request_from}</d>")

                    # XML Generation (releases are already sliced)
                    items = ""
                    now_rfc822 = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

                    for release in releases:
                        release = release.get("details", {})

                        # Ensure clean XML output
                        title = str(release.get("title", "") or "")
                        source = str(release.get("source", "") or "")
                        if not title:
                            debug(f"Title missing for release from {source}")
                            continue

                        if extract_client_type(request_from) != "magazarr":
                            title = f"[{release.get('hostname', '').upper()}] {title}"

                        # Get publication date - sources should provide valid dates
                        pub_date = release.get("date", "").strip()
                        if not pub_date:
                            pub_date = now_rfc822

                        title_xml = _xml_text(title)
                        link_xml = _xml_text(release.get("link", ""))
                        source_xml = _xml_text(source)
                        pub_date_xml = _xml_text(pub_date)
                        enclosure_url = _xml_attr(release.get("link", ""))
                        enclosure_length = _xml_attr(release.get("size", 0))

                        items += f"""
                        <item>
                            <title>{title_xml}</title>
                            <guid isPermaLink="True">{link_xml}</guid>
                            <link>{link_xml}</link>
                            <comments>{source_xml}</comments>
                            <pubDate>{pub_date_xml}</pubDate>
                            <enclosure url={enclosure_url} length={enclosure_length} type="application/x-nzb" />
                        </item>"""

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
                            <pubDate>{now_rfc822}</pubDate>
                            <enclosure url="https://github.com/rix1337/Quasarr" length="0" type="application/x-nzb" />
                        </item>"""

                    return f"""<?xml version="1.0" encoding="UTF-8"?>
                                <rss>
                                    <channel>
                                        <title>Quasarr Indexer</title>
                                        <description>Quasarr Indexer API</description>
                                        <link>https://quasarr.indexer/</link>
                                        <pubDate>{now_rfc822}</pubDate>
                                        {items}
                                    </channel>
                                </rss>"""
            except Exception as e:
                error(f"Error loading search results: {e} " + traceback.format_exc())
            warn(f"Unknown indexer request: {dict(request.query)}")
            now_rfc822 = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
            return f"""<?xml version="1.0" encoding="UTF-8"?>
                        <rss>
                            <channel>
                                <title>Quasarr Indexer</title>
                                <description>Quasarr Indexer API</description>
                                <link>https://quasarr.indexer/</link>
                                <pubDate>{now_rfc822}</pubDate>
                            </channel>
                        </rss>"""

        warn(f"[ERROR] Unknown general request: {dict(request.query)}")
        return {"error": True}
