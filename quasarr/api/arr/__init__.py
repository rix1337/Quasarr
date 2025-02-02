# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import traceback
import xml.sax.saxutils as sax_utils
from base64 import urlsafe_b64decode
from datetime import datetime
from functools import wraps
from xml.etree import ElementTree

from bottle import abort, request

from quasarr.downloads import download, delete_package, get_packages
from quasarr.providers import shared_state
from quasarr.providers.log import info, debug
from quasarr.providers.tvmaze_metadata import get_title_from_tvrage_id
from quasarr.search import get_search_results
from quasarr.storage.config import Config


def require_api_key(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        api_key = Config('API').get('key')
        if not request.query.apikey:
            return abort(401, "Missing API key")
        if request.query.apikey != api_key:
            return abort(403, "Invalid API key")
        return func(*args, **kwargs)

    return decorated


def setup_arr_routes(app):
    @app.get('/download/')
    def fake_nzb_file():
        payload = request.query.payload
        decoded_payload = urlsafe_b64decode(payload).decode("utf-8").split("|")
        title = decoded_payload[0]
        url = decoded_payload[1]
        size_mb = decoded_payload[2]
        password = decoded_payload[3]
        imdb_id = decoded_payload[4]
        return f'<nzb><file title="{title}" url="{url}" size_mb="{size_mb}" password="{password}" imdb_id="{imdb_id}"/></nzb>'

    @app.post('/api')
    @require_api_key
    def download_fake_nzb_file():
        downloads = request.files.getall('name')
        nzo_ids = []
        for upload in downloads:
            file_content = upload.file.read()
            root = ElementTree.fromstring(file_content)
            title = sax_utils.unescape(root.find(".//file").attrib["title"])
            url = root.find(".//file").attrib["url"]
            size_mb = root.find(".//file").attrib["size_mb"]
            password = root.find(".//file").attrib.get("password")
            imdb_id = root.find(".//file").attrib.get("imdb_id")
            info(f"Attempting download for {title}")

            request_from = request.headers.get('User-Agent')

            nzo_id = download(shared_state, request_from, title, url, size_mb, password, imdb_id)
            if nzo_id:
                info(f"{title} added successfully!")
                nzo_ids.append(nzo_id)
            else:
                info(f"{title} could not be added!")

        return {
            "status": True,
            "nzo_ids": nzo_ids
        }

    @app.get('/api')
    @require_api_key
    def fake_sabnzbd_and_newznab_apis():
        api_type = 'sabnzbd' if request.query.mode else 'newznab' if request.query.t else None

        if api_type == 'sabnzbd':
            try:
                mode = request.query.mode
                if mode == "version":
                    return {
                        "version": "4.3.2"
                    }
                elif mode == "get_config":
                    return {
                        "config": {
                            "misc": {
                                "quasarr": True,
                                "complete_dir": "/tmp/"
                            },
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
                                }
                            ]
                        }
                    }
                elif mode == "fullstatus":
                    return {
                        "status": {
                            "quasarr": True
                        }
                    }
                elif mode == "queue" or mode == "history":
                    if request.query.name and request.query.name == "delete":
                        package_id = request.query.value
                        deleted = delete_package(shared_state, package_id)
                        return {
                            "status": deleted,
                            "nzo_ids": [package_id]
                        }

                    packages = get_packages(shared_state)
                    if mode == "queue":
                        return {
                            "queue": {
                                "paused": False,
                                "slots": packages["queue"]
                            }
                        }
                    elif mode == "history":
                        return {
                            "history": {
                                "paused": False,
                                "slots": packages["history"]
                            }
                        }
            except Exception as e:
                info(f"Error loading packages: {e}")
                info(traceback.format_exc())
            return {
                "status": False
            }

        elif api_type == 'newznab':
            try:
                mode = request.query.t
                if mode == 'caps':
                    return '''<?xml version="1.0" encoding="UTF-8"?>
                                    <caps>
                                      <categories>
                                          <category id="2000" name="Movies">
                                          </category>
                                          <category id="5000" name="TV">
                                          </category>
                                      </categories>
                                    </caps>'''
                elif mode in ['movie', 'tvsearch', 'search']:
                    request_from = request.headers.get('User-Agent')

                    releases = []

                    if mode == 'movie':
                        # only imdb is implemented
                        search_param = f"tt{getattr(request.query, 'imdbid', '')}" \
                            if getattr(request.query, 'imdbid', '') else ""

                        releases = get_search_results(shared_state, request_from, search_string=search_param)

                    elif mode == 'search':
                        debug(f'Search in Anime-Order is not supported. Ignoring request: {dict(request.query)}')

                    elif mode == 'tvsearch':
                        # these are currently ignored, Sonarr handles them anyway
                        season = getattr(request.query, 'season', "")
                        episode = getattr(request.query, 'ep', "")
                        # only plain search string and tvrage id is implemented
                        search_param = getattr(request.query, 'q', "")
                        if not search_param:
                            tvrage_id = getattr(request.query, 'rid', "")
                            if tvrage_id:
                                search_param = get_title_from_tvrage_id(tvrage_id)

                        offset = getattr(request.query, 'offset', "")  # ignoring offset higher than 0 on purpose
                        if int(offset) == 0:
                            releases = get_search_results(shared_state, request_from,
                                                          search_string=search_param,
                                                          season=season,
                                                          episode=episode
                                                          )
                        else:
                            debug(f'Offset higher than 0 is not supported. Ignoring request: {dict(request.query)}')

                    items = ""
                    if not releases:
                        items += f'''
                            <item>
                                <title>No releases found</title>
                                <link></link>
                                <pubDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>
                                <enclosure url="_" length="0" type="application/x-nzb"/>
                                <guid></guid>
                                <comments></comments>
                                <description></description>
                            </item>'''

                    for release in releases:
                        release = release["details"]
                        items += f'''
                        <item>
                            <title>{sax_utils.escape(release["title"])}</title>
                            <guid isPermaLink="True">{release["link"]}</guid>
                            <link>{release["link"]}</link>
                            <comments>{release["source"]}</comments>
                            <pubDate>{release["date"]}</pubDate>
                            <enclosure url="{release["link"]}" length="{release["size"]}" type="application/x-nzb" />
                        </item>'''

                    return f'''<?xml version="1.0" encoding="UTF-8"?>
                                <rss version="2.0">
                                    <channel>
                                        {items}
                                    </channel>
                                </rss>'''
            except Exception as e:
                info(f"Error loading search results: {e}")
                info(traceback.format_exc())

            info(f"Unknown request: {dict(request.query)}")
            return {"error": True}
